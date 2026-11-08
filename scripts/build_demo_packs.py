"""生成帮助页「示例工作区」归档包（需求 0106）.

发布前运行一次，把 `cndb seed` 产出的两套演示工作区导出为工作区备份归档
（ADR 0075 格式，`include_secrets=False`），写入 `examples/demo-packs/`，随
wheel / fspack 一起发布。日常开发不需要重新生成。

用法：
    uv run python scripts/build_demo_packs.py

实现要点：
- 使用临时 `CNDB_DATA_DIR`，不触碰本机 `~/.cndb` 的真实数据；
- 直接在进程内调用 seed（空库，正常执行），再按场景导出归档；
- 归档导入由 `plugins/workspaces` 负责重映射 ID，与 `POST /import/archive` 同口径。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

SCENARIOS: dict[str, str] = {
    "sales": "某企业销售管理",
    "research": "科研项目管理（模板示例）",
}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "examples" / "demo-packs"
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = Path(tempfile.mkdtemp(prefix="cndb-demo-packs-"))
    os.environ["CNDB_DATA_DIR"] = str(temp_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{temp_dir / 'cndb.db'}"

    try:
        from cndb.cli.seed import seed

        seed(None)

        from sqlalchemy import select

        from cndb.core.database import SessionLocal
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import Workspace
        from cndb.plugins.workspaces.services.workspace_backup import (
            build_workspace_backup_v9,
            pack_workspace_archive,
        )

        db = SessionLocal()
        try:
            owner = db.execute(select(User).where(User.username == "admin")).scalar_one()
            for key, workspace_name in SCENARIOS.items():
                workspace = db.execute(
                    select(Workspace).where(Workspace.name == workspace_name).limit(1)
                ).scalar_one_or_none()
                if workspace is None:
                    raise SystemExit(f"[demo-packs] 未找到演示工作区: {workspace_name}")

                backup, files = build_workspace_backup_v9(db, workspace.id, owner, include_secrets=False)
                target = output_dir / f"{key}.tar.gz"
                pack_workspace_archive(backup, files, target)
                print(f"[demo-packs] {key}: {target.relative_to(root)} ({target.stat().st_size} bytes)")
        finally:
            db.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

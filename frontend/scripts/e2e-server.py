"""E2E 后端一键启动（供 Playwright webServer 使用）。

流程：数据目录隔离（.e2e-data，绝不触碰用户 ~/.cndb）→ seed 注入演示数据
（幂等 drop_all 重建）→ 启动后端:8000。
前置：前端已构建到 src/cndb/static（make frontend-build / pnpm build）。
跨平台（Windows/macOS/Linux），替代 bash/PowerShell 脚本。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    # 定位项目根目录（scripts/ → frontend/ → 项目根）
    root = Path(__file__).resolve().parent.parent.parent
    os.chdir(root)

    port = os.environ.get("E2E_PORT", "8000")

    # ── 数据目录隔离 ──
    # 通过 CNDB_DATA_DIR 把数据库/上传/日志等整体重定向到仓库内 .e2e-data，
    # 与用户真实数据（~/.cndb）完全隔离：测试的增删改不会污染用户数据，
    # 用户数据也不会破坏 seed 后的稳定假设（如 ws id=1 为某企业销售管理）。
    e2e_data = root / ".e2e-data"
    if e2e_data.exists():
        shutil.rmtree(e2e_data)  # 每轮全量重建，防 uploads 等残留累积
    os.environ["CNDB_DATA_DIR"] = str(e2e_data)
    # DATABASE_URL 显式覆盖（环境变量优先级高于 ~/.cndb/config/.env）
    os.environ["DATABASE_URL"] = f"sqlite:///{(e2e_data / 'data' / 'cndb.db').as_posix()}"
    print(f"[e2e-server] 数据目录隔离: {e2e_data}", flush=True)

    print("[e2e-server] seed 演示数据...", flush=True)
    seed = subprocess.run(
        ["uv", "run", "cndb", "seed"],
        cwd=root,
    )
    if seed.returncode != 0:
        print(f"[e2e-server] seed 失败 (exit={seed.returncode})", file=sys.stderr, flush=True)
        return seed.returncode

    print(f"[e2e-server] 启动后端 http://127.0.0.1:{port} ...", flush=True)
    # exec 语义：用 serve 进程替换当前进程，Playwright 能正确感知进程生命周期
    return subprocess.call(
        ["uv", "run", "cndb", "serve", "--host", "127.0.0.1", "--port", port],
        cwd=root,
    )


if __name__ == "__main__":
    sys.exit(main())

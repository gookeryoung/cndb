"""结构设计种子：各工作区 `designs/*.cnmd`（ADR 0079 P2）.

对齐 pipelines/ 目录范式：一份 `.cnmd` 文件 = 一份结构设计，**文件名（去后缀）
即设计标题**（结构 DSL 无 name 语句，标题不入 DSL 原文）。seed 期经
``compile_design`` 全量编译校验，非法样例打印告警并跳过，不落库、不阻断
其它种子；只注入定义（本体 + v1 版本），不触发导出等动作。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import paths


def _seed_designs(
    db: Any,
    user: Any,
    ws_map: dict[str, Any],
    datasets_dir: Path | None,
) -> int:
    """按各工作区文件夹下的 designs/*.cnmd 注入结构设计.

    幂等：同 ``(workspace_id, title)`` 已有设计则跳过；编译失败打印告警并
    跳过该文件。Returns: 新建设计数量。
    """
    from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
    from cndb.plugins.design.services.dsl.compile import compile_design
    from cndb.plugins.design.services.keys import generate_file_key

    if datasets_dir is None:
        print("[seed-设计] examples/datasets 目录不存在，跳过设计注入")
        return 0

    ws_cnmds = paths._get_workspace_design_cnmds(datasets_dir)
    if not ws_cnmds:
        print("[seed-设计] 未发现任何 designs/*.cnmd，跳过设计注入")
        return 0

    created = 0
    for ws_name, cnmds in ws_cnmds.items():
        ws = ws_map.get(ws_name)
        if ws is None:
            print(f"[seed-设计] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        for path in cnmds:
            title = path.stem
            label = f"{ws_name}/{path.name}"
            try:
                content = path.read_text(encoding="utf-8-sig")
                result = compile_design(content)
            except Exception as exc:  # 编译 / 读取失败：跳过该样例
                print(f"[seed-设计] 跳过: {label} 编译失败（{exc}）")
                continue
            if not result.ok:
                first = result.diagnostics[0].message if result.diagnostics else "未知错误"
                print(f"[seed-设计] 跳过: {label} 编译失败（{first}）")
                continue
            existing = (
                db.query(DesignDesign).filter(DesignDesign.workspace_id == ws.id, DesignDesign.title == title).first()
            )
            if existing is not None:
                print(f"[seed-设计] 已存在，跳过: {label} → {title}")
                continue
            ir = result.ir or {"version": 1, "nodes": []}
            design = DesignDesign(
                workspace_id=ws.id,
                title=title,
                file_key=generate_file_key(db, ws.id, title),
                content=content,
                compiled=ir,
                created_by_id=user.id if user is not None else None,
                updated_by_id=user.id if user is not None else None,
            )
            db.add(design)
            db.flush()
            # 「创建即 v1」口径与 API 一致（ADR 0079 D7）
            db.add(
                DesignDesignVersion(
                    design_id=design.id,
                    workspace_id=ws.id,
                    version_number=1,
                    content=content,
                    compiled=ir,
                    created_by_id=user.id if user is not None else None,
                )
            )
            db.flush()
            created += 1
            nodes = len(ir.get("nodes", []))
            print(f"[seed-设计] {label} → {title}（{nodes} 个顶层实例）")

    db.commit()
    return created


__all__ = ["_seed_designs"]

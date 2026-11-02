"""结构设计种子：各工作区 `designs/**/*.cnmd`（ADR 0079 P2 / 0086 §6 分文件）.

对齐 pipelines/ 目录范式：一份 `.cnmd` 文件 = 一份设计文件，**文件名（去后缀）
即设计标题**。目录口径（ADR 0086 §6）：顶层 `designs/*.cnmd` 为装配文件
（kind=assembly，folder 取相对目录）；`designs/parts/*.cnmd` 为零件文件
（kind=part，folder="parts"）。装配用 `use "<file_key>"` 引用零件，file_key
由标题清洗生成（`generate_file_key`，中文保留）。

注入两阶段（I2/I3）：先建全部零件行拿到 file_id，再以 `build_resolver`
按当前库内 file_key 解析编译装配并写依赖闭包（design.dependencies + 版本
dependencies + design_designref）。seed 期经 ``compile_design`` 全量校验，
非法样例打印告警并跳过，不落库、不阻断其它种子；只注入定义（本体 + v1
版本），不触发导出等动作。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import paths


def _design_kind(folder: str) -> str:
    """种子目录 → 文件类型：首段 parts/ 为零件，顶层（或其它目录）为装配."""
    return "part" if folder.split("/", 1)[0] == "parts" else "assembly"


def _seed_designs(
    db: Any,
    user: Any,
    ws_map: dict[str, Any],
    datasets_dir: Path | None,
) -> int:
    """按各工作区文件夹下的 designs/**/*.cnmd 注入设计文件（两阶段）.

    幂等：同 ``(workspace_id, folder, title)`` 已有设计则跳过；编译失败打印
    告警并跳过该文件。Returns: 新建设计数量。
    """
    from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
    from cndb.plugins.design.services.dsl.compile import compile_design
    from cndb.plugins.design.services.files import build_resolver, sync_refs
    from cndb.plugins.design.services.keys import generate_file_key

    if datasets_dir is None:
        print("[seed-设计] examples/datasets 目录不存在，跳过设计注入")
        return 0

    ws_files = paths._get_workspace_design_cnmds(datasets_dir)
    if not ws_files:
        print("[seed-设计] 未发现任何 designs/**/*.cnmd，跳过设计注入")
        return 0

    created = 0
    for ws_name, entries in ws_files.items():
        ws = ws_map.get(ws_name)
        if ws is None:
            print(f"[seed-设计] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        user_id = user.id if user is not None else None

        for phase in ("part", "assembly"):
            for folder, path in entries:
                if _design_kind(folder) != phase:
                    continue
                title = path.stem
                designs_dir = next(p for p in path.parents if p.name == "designs")
                label = f"{ws_name}/{path.relative_to(designs_dir).as_posix()}"
                try:
                    content = path.read_text(encoding="utf-8-sig")
                    if phase == "part":
                        result = compile_design(content, file_kind="part")
                    else:
                        result = compile_design(content, file_kind="assembly", resolver=build_resolver(db, ws.id))
                except Exception as exc:  # 编译 / 读取失败：跳过该样例
                    print(f"[seed-设计] 跳过: {label} 编译失败（{exc}）")
                    continue
                if not result.ok:
                    first = result.diagnostics[0].message if result.diagnostics else "未知错误"
                    print(f"[seed-设计] 跳过: {label} 编译失败（{first}）")
                    continue
                existing = (
                    db.query(DesignDesign)
                    .filter(
                        DesignDesign.workspace_id == ws.id,
                        DesignDesign.folder == folder,
                        DesignDesign.title == title,
                    )
                    .first()
                )
                if existing is not None:
                    print(f"[seed-设计] 已存在，跳过: {label} → {folder or '<顶层>'}/{title}")
                    continue
                ir = result.ir or {"version": 1, "nodes": []}
                deps = [
                    {
                        "file_id": item.file_id,
                        "file_key": item.file_key,
                        "version_number": item.version_number,
                        "content_hash": item.content_hash,
                    }
                    for item in result.dependencies
                ]
                design = DesignDesign(
                    workspace_id=ws.id,
                    title=title,
                    kind=phase,
                    file_key=generate_file_key(db, ws.id, title),
                    folder=folder,
                    content=content,
                    compiled=ir,
                    dependencies=deps,
                    created_by_id=user_id,
                    updated_by_id=user_id,
                )
                db.add(design)
                db.flush()
                # 「创建即 v1」口径与 API 一致（ADR 0079 D7；v4 起版本带依赖闭包）
                db.add(
                    DesignDesignVersion(
                        design_id=design.id,
                        workspace_id=ws.id,
                        version_number=1,
                        content=content,
                        compiled=ir,
                        dependencies=deps,
                        created_by_id=user_id,
                    )
                )
                if phase == "assembly" and deps:
                    sync_refs(db, design, [item["file_key"] for item in deps])
                db.flush()
                created += 1
                nodes = len(ir.get("nodes", []))
                kind_label = "零件" if phase == "part" else "装配"
                print(f"[seed-设计] {label} → {kind_label} {title}（{nodes} 个顶层实例）")

        db.commit()

    return created


__all__ = ["_seed_designs"]

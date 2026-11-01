"""质量检查流水线种子：各工作区 `pipelines/*.yaml`（ADR 0076）.

对齐 documents/ 目录范式：一份 YAML 文件 = 一条流水线定义（``name`` 写在 DSL 内），
seed 期经 ``compile_workflow`` 全量编译校验（结构 / 动作注册表 / ``with`` schema /
表达式语法），并把 ``with.table`` 引用的表名解析校验到当前工作区真实表。
非法样例打印告警并跳过，不落库、不阻断其它种子；只注入定义，不触发运行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import paths


def _validate_table_refs(ir: Any, ws_tables: dict[str, Any]) -> str | None:
    """校验 IR 内全部 ``with.table`` 引用存在于当前工作区.

    Returns:
        不通过时返回首个缺失表名的告警文本；通过返回 None。
    """
    for job in ir.jobs:
        for step in job.steps:
            table_name = step.params.get("table")
            if isinstance(table_name, str) and table_name not in ws_tables:
                return f"引用的表 '{table_name}' 不存在"
    return None


def _seed_pipelines(
    db: Any,
    user: Any,
    ws_map: dict[str, Any],
    tables_map: dict[str, dict[str, Any]],
    datasets_dir: Path | None,
) -> int:
    """按各工作区文件夹下的 pipelines/*.yaml 注入流水线定义.

    幂等：同 ``(workspace_id, name)`` 已有定义则跳过；编译失败 / 表引用缺失
    打印告警并跳过该文件。Returns: 新建定义数量。
    """
    from cndb.plugins.pipeline.models import PipelineWorkflow
    from cndb.plugins.pipeline.services.dsl.parse import compile_workflow

    if datasets_dir is None:
        print("[seed-流水线] examples/datasets 目录不存在，跳过流水线注入")
        return 0

    ws_yamls = paths._get_workspace_pipeline_yamls(datasets_dir)
    if not ws_yamls:
        print("[seed-流水线] 未发现任何 pipelines/*.yaml，跳过流水线注入")
        return 0

    created = 0
    for ws_name, yamls in ws_yamls.items():
        ws = ws_map.get(ws_name)
        if ws is None:
            print(f"[seed-流水线] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        ws_tables = tables_map.get(ws_name) or {}
        for path in yamls:
            label = f"{ws_name}/{path.name}"
            try:
                content = path.read_text(encoding="utf-8-sig")
                ir = compile_workflow(content)
            except Exception as exc:  # DslError / 文件读取失败：跳过该样例
                print(f"[seed-流水线] 跳过: {label} 编译失败（{exc}）")
                continue
            ref_error = _validate_table_refs(ir, ws_tables)
            if ref_error is not None:
                print(f"[seed-流水线] 跳过: {label} {ref_error}")
                continue
            existing = (
                db.query(PipelineWorkflow)
                .filter(PipelineWorkflow.workspace_id == ws.id, PipelineWorkflow.name == ir.name)
                .first()
            )
            if existing is not None:
                print(f"[seed-流水线] 已存在，跳过: {label} → {ir.name}")
                continue
            db.add(
                PipelineWorkflow(
                    workspace_id=ws.id,
                    name=ir.name,
                    content=content,
                    compiled=ir.to_dict(),
                    enabled=True,
                    created_by_id=user.id if user is not None else None,
                )
            )
            db.flush()
            created += 1
            print(f"[seed-流水线] {label} → {ir.name}（{len(ir.jobs)} 个 job）")

    db.commit()
    return created


__all__ = ["_seed_pipelines"]

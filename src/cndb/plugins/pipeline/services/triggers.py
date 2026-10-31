"""流水线事件触发分发（ADR 0076 D5 / P1）.

三个既有写路径在事务提交后调用 :func:`dispatch_event`：

- 记录批量变更（批量建行 / 删行 / 改行）→ ``record.updated``
- 文档正文保存（直编落库）→ ``document.saved``
- 数据源同步完成（成功或失败）→ ``sync.finished``

分发是**尽力而为**：异常只记日志，绝不把调用方的业务事务带崩（与 ``record_event``
同口径）。命中的定义按 ``compiled.on.events`` 判定，``enabled=false`` 不响应事件
（边界 6）；同一定义已有活跃运行时静默跳过（单飞语义，I6 / D8）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from cndb.plugins.pipeline.models import (
    TRIGGER_EVENT,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.services.dsl.parse import WorkflowIR
from cndb.plugins.pipeline.services.errors import PipelineConflictError
from cndb.plugins.pipeline.services.runner import (
    create_run,
    run_pipeline_in_background,
)

logger = logging.getLogger(__name__)

#: 记录批量变更事件（批量建行 / 删行 / 改行）
EVENT_RECORD_UPDATED = "record.updated"
#: 文档正文保存事件（直编落库）
EVENT_DOCUMENT_SAVED = "document.saved"
#: 数据源同步完成事件（成功或失败）
EVENT_SYNC_FINISHED = "sync.finished"

#: 当前支持的事件集合（与前端检查目录 / DSL 文档同步）
SUPPORTED_EVENTS = (EVENT_RECORD_UPDATED, EVENT_DOCUMENT_SAVED, EVENT_SYNC_FINISHED)


def event_workflows(db: Session, workspace_id: int, event: str) -> list[PipelineWorkflow]:
    """返回工作区内启用且订阅了 ``event`` 的流水线定义."""
    rows = (
        db.query(PipelineWorkflow)
        .filter(
            PipelineWorkflow.workspace_id == workspace_id,
            PipelineWorkflow.enabled == True,  # noqa: E712 - SQLAlchemy 表达式
        )
        .order_by(PipelineWorkflow.id)
        .all()
    )
    matched: list[PipelineWorkflow] = []
    for workflow in rows:
        try:
            ir = WorkflowIR.from_dict(workflow.compiled or {})
        except Exception:  # pragma: no cover - 保存期已编译，历史脏数据兜底
            logger.warning("流水线 %s 编译快照损坏，跳过事件触发", workflow.id)
            continue
        events = ir.triggers.get("events") or ()
        if isinstance(events, str):
            events = (events,)
        if event in events:
            matched.append(workflow)
    return matched


def dispatch_event(
    db: Session,
    event: str,
    *,
    workspace_id: int,
    payload: dict[str, Any] | None = None,
) -> list[int]:
    """按事件触发命中的流水线，返回新建的运行 ID 列表（失败静默返回空）.

    Args:
        db: 调用方会话（仅用于读定义与建运行记录；调用前业务数据应已提交）。
        event: 事件名（``record.updated`` / ``document.saved`` / ``sync.finished``）。
        workspace_id: 事件所属工作区。
        payload: 触发上下文（进入 ``on.*`` 表达式），不含业务字段值（D7）。
    """
    if event not in SUPPORTED_EVENTS:
        logger.warning("未知的流水线事件：%s", event)
        return []
    body = dict(payload or {})
    body["event"] = event
    try:
        workflows = event_workflows(db, workspace_id, event)
        if not workflows:
            return []
        factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
        run_ids: list[int] = []
        for workflow in workflows:
            try:
                run = create_run(db, workflow, trigger=TRIGGER_EVENT, payload=body)
            except PipelineConflictError:
                logger.info("流水线 %s 已有活跃运行，跳过事件触发", workflow.id)
                continue
            run_ids.append(run.id)
        for run_id in run_ids:
            run_pipeline_in_background(factory, run_id)
        return run_ids
    except Exception:
        # 事件分发失败不影响业务写入（与 record_event 的尽力而为口径一致）
        logger.exception("流水线事件分发失败：%s @ workspace=%s", event, workspace_id)
        return []


__all__ = [
    "EVENT_DOCUMENT_SAVED",
    "EVENT_RECORD_UPDATED",
    "EVENT_SYNC_FINISHED",
    "SUPPORTED_EVENTS",
    "dispatch_event",
    "event_workflows",
]

"""流水线定义版本历史：唯一落版入口与版本对比（ADR 0114 §2）.

路由层不得自行拼 ``PipelineWorkflowVersion``（I1），所有版本行只经
``add_workflow_version`` 追加；diff 统一走 ``core.textdiff.unified_diff``（I2）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import NotFoundError
from cndb.core.textdiff import unified_diff
from cndb.plugins.accounts.models import User
from cndb.plugins.pipeline.models import PipelineWorkflow, PipelineWorkflowVersion

__all__ = [
    "add_workflow_version",
    "get_workflow_version",
    "latest_version_number",
    "workflow_diff",
]


def latest_version_number(db: Session, workflow_id: int) -> int:
    """取定义当前最大版本号（无版本返回 0）."""
    row = (
        db.query(PipelineWorkflowVersion.version_number)
        .filter(PipelineWorkflowVersion.workflow_id == workflow_id)
        .order_by(PipelineWorkflowVersion.version_number.desc())
        .first()
    )
    return int(row[0]) if row is not None else 0


def add_workflow_version(
    db: Session,
    workflow: PipelineWorkflow,
    user: User,
    *,
    content: str,
    change_type: str,
    comment: str = "",
) -> int:
    """为定义追加一个版本快照，返回版本号（不 commit，由调用方事务提交）."""
    number = latest_version_number(db, workflow.id) + 1
    db.add(
        PipelineWorkflowVersion(
            workspace_id=workflow.workspace_id,
            workflow_id=workflow.id,
            version_number=number,
            change_type=change_type,
            content=content,
            comment=comment,
            created_by_id=user.id,
        )
    )
    return number


def get_workflow_version(db: Session, workflow: PipelineWorkflow, version_number: int) -> PipelineWorkflowVersion:
    """按定义 + 版本号取版本行（不存在 404 ``pipeline_version_not_found``）."""
    version = (
        db.query(PipelineWorkflowVersion)
        .filter(
            PipelineWorkflowVersion.workflow_id == workflow.id,
            PipelineWorkflowVersion.version_number == version_number,
        )
        .first()
    )
    if version is None:
        raise NotFoundError("流水线版本不存在", code="pipeline_version_not_found")
    return version


def workflow_diff(db: Session, workflow: PipelineWorkflow, base: int, head: int) -> dict[str, Any]:
    """两版本 unified diff（任一版本不存在 404）."""
    base_row = get_workflow_version(db, workflow, base)
    head_row = get_workflow_version(db, workflow, head)
    diff_text, added, removed = unified_diff(base_row.content, head_row.content)
    return {
        "base_version": base_row.version_number,
        "head_version": head_row.version_number,
        "diff": diff_text,
        "added": added,
        "removed": removed,
    }

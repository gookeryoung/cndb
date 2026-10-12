"""表级「编辑需审批」分派：records/forms 写端点共用.

语义：开关（DataTable.edit_approval_workflow_id）开启时提交变更单，
审批通过才落库；关闭返回 None，调用方走直编直存。
分派点只在路由层（records POST/PATCH/DELETE + forms PATCH），
service 层不感知开关。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.workflows.models import Workflow
from cndb.plugins.workflows.services.approval import (
    ApprovalConflictError,
    submit_change_request,
)


def dispatch_edit_approval(
    db: Session,
    dt: DataTable,
    user: User,
    *,
    op: str,
    row_id: int | None,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    """编辑审批开关分派：开启时提交变更单并返回审批载荷，关闭返回 None.

    三个网格入口（单元格/整行/Drawer）、新增与删除、表单编辑共用同一
    分派语义；防叠加守卫在 submit_change_request 内（同行在途 → 409）。

    Args:
        db: 数据库会话（本函数内部 commit）。
        dt: 目标数据表。
        user: 提交人。
        op: 变更操作类型，见 CHANGE_OPS。
        row_id: update/delete 的目标行 id；create 为 None。
        values: 变更值快照（update 存增量）。

    Returns:
        开关开启：{"approval": {...}} 载荷，调用方须置响应 202；
        开关关闭：None，调用方走直编直存。

    Raises:
        HTTPException: 409 绑定审批流不存在 / 同行已有在途变更。
    """
    if dt.edit_approval_workflow_id is None:
        return None
    workflow = db.get(Workflow, dt.edit_approval_workflow_id)
    if workflow is None:
        raise HTTPException(status_code=409, detail="编辑审批开关绑定的审批流已不存在，请调整表设置")
    try:
        instance = submit_change_request(db, dt, workflow, op, row_id, values, user)
    except ApprovalConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {
        "approval": {
            "id": instance.id,
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "status": instance.status,
            "op": instance.op,
            "row_id": instance.row_id,
            "current_approver_role": instance.current_approver_role,
        }
    }


__all__ = ["dispatch_edit_approval"]

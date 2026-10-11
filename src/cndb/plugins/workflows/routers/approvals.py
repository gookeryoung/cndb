"""审批实例路由：待办/我提交的列表 + 批准/驳回.

错误映射：ApprovalPermissionError → 403；ApprovalConflictError → 409。
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workflows.schemas.models import ApprovalActionCreate, ApprovalInstanceResponse
from cndb.plugins.workflows.services.approval import (
    ApprovalConflictError,
    ApprovalPermissionError,
    act_on_instance,
    decorate_instance,
    list_instances,
)
from cndb.plugins.workspaces.models import Workspace
from cndb.plugins.workspaces.permissions import get_member_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/{workspace_id}/approvals", tags=["workflows"])


def _get_workspace_or_404(db: Session, workspace_id: int) -> Workspace:
    """加载工作区，不存在抛 404."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


def _require_member(db: Session, ws: Workspace, user: User) -> None:
    """要求当前用户为工作区成员，否则 403."""
    if get_member_role(user, ws, db) is None:
        raise HTTPException(status_code=403, detail="仅工作区成员可访问审批")


@router.get("", response_model=list[ApprovalInstanceResponse])
def list_approvals(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    scope: Literal["pending_for_me", "mine"] = Query(default="pending_for_me"),
    form_id: int | None = Query(default=None),
) -> list[ApprovalInstanceResponse]:
    """查询审批实例：scope=pending_for_me 待我审批 / mine 我提交的."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_member(db, ws, current_user)
    items = list_instances(db, workspace_id, scope, current_user, form_id=form_id)
    return [ApprovalInstanceResponse(**decorate_instance(db, it)) for it in items]


def _act(
    db: Session,
    workspace_id: int,
    instance_id: int,
    current_user: User,
    action: str,
    payload: ApprovalActionCreate,
) -> ApprovalInstanceResponse:
    """approve/reject 共用处理：异常到 HTTP 的映射收敛于此."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_member(db, ws, current_user)
    try:
        instance = act_on_instance(db, instance_id, current_user, action, payload.comment)
    except ApprovalPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(instance)
    return ApprovalInstanceResponse(**decorate_instance(db, instance))


@router.post("/{instance_id}/approve", response_model=ApprovalInstanceResponse)
def approve_instance(
    workspace_id: int,
    instance_id: int,
    payload: ApprovalActionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalInstanceResponse:
    """批准当前节点（链尾通过则落库并终态 approved）."""
    return _act(db, workspace_id, instance_id, current_user, "approve", payload)


@router.post("/{instance_id}/reject", response_model=ApprovalInstanceResponse)
def reject_instance(
    workspace_id: int,
    instance_id: int,
    payload: ApprovalActionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalInstanceResponse:
    """驳回当前节点（实例终态 rejected，数据不落库）."""
    return _act(db, workspace_id, instance_id, current_user, "reject", payload)


__all__ = ["router"]

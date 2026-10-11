"""审批流定义 CRUD 路由（工作区级，整图保存）.

权限模型：
- 管理（创建/更新/删除）= 工作区角色 admin 及以上
- 查看（列表/详情）= 工作区任意成员
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workflows.models import Workflow
from cndb.plugins.workflows.schemas.models import (
    WorkflowListItemResponse,
    WorkflowResponse,
    WorkflowSave,
)
from cndb.plugins.workflows.services.graph import (
    load_graph_dto,
    save_graph,
    validate_graph_payload,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}/workflows", tags=["workflows"])


def _get_workspace_or_404(db: Session, workspace_id: int) -> Workspace:
    """加载工作区，不存在抛 404."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


def _require_member(db: Session, ws: Workspace, user: User) -> None:
    """要求当前用户为工作区成员，否则 403."""
    if get_member_role(user, ws, db) is None:
        raise HTTPException(status_code=403, detail="仅工作区成员可访问审批流")


def _require_admin(db: Session, ws: Workspace, user: User) -> None:
    """要求当前用户为工作区 admin 及以上，否则 403."""
    from cndb.plugins.workspaces.permissions import has_role

    if not has_role(user, ws, WorkspaceRole.ADMIN, db):
        raise HTTPException(status_code=403, detail="审批流管理需要 admin 及以上角色")


def _workflow_response(db: Session, wf: Workflow) -> WorkflowResponse:
    """Workflow ORM → 详情响应（含整图）."""
    nodes, edges = load_graph_dto(db, wf)
    return WorkflowResponse(
        id=wf.id,
        workspace_id=wf.workspace_id,
        name=wf.name,
        description=wf.description,
        order=wf.order,
        nodes=nodes,  # type: ignore[arg-type]
        edges=edges,  # type: ignore[arg-type]
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


@router.get("", response_model=list[WorkflowListItemResponse])
def list_workflows(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkflowListItemResponse]:
    """列出工作区内全部审批流（任意成员可见）."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_member(db, ws, current_user)
    items = db.query(Workflow).filter(Workflow.workspace_id == workspace_id).order_by(Workflow.order, Workflow.id).all()
    return [WorkflowListItemResponse.model_validate(wf) for wf in items]


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workspace_id: int,
    payload: WorkflowSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """创建审批流（admin 及以上；图校验失败返回 400 明细）."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_admin(db, ws, current_user)
    errors = validate_graph_payload(payload.nodes, payload.edges)
    if errors:
        raise HTTPException(status_code=400, detail=f"审批流校验失败: {'; '.join(errors)}")
    wf = Workflow(workspace_id=workspace_id, name=payload.name, description=payload.description, order=payload.order)
    db.add(wf)
    db.flush()
    save_graph(db, wf, payload.nodes, payload.edges)
    db.commit()
    db.refresh(wf)
    return _workflow_response(db, wf)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """获取审批流详情（含整图）."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_member(db, ws, current_user)
    wf = db.get(Workflow, workflow_id)
    if wf is None or wf.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="审批流不存在")
    return _workflow_response(db, wf)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workspace_id: int,
    workflow_id: int,
    payload: WorkflowSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """更新审批流（整图覆盖；admin 及以上）.

    注意：重存会重建节点 id，存量 pending 实例的 current_node_id 被
    SET NULL 置空，审批按链上首个审批节点兜底继续（见 services.approval）。
    """
    ws = _get_workspace_or_404(db, workspace_id)
    _require_admin(db, ws, current_user)
    wf = db.get(Workflow, workflow_id)
    if wf is None or wf.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="审批流不存在")
    errors = validate_graph_payload(payload.nodes, payload.edges)
    if errors:
        raise HTTPException(status_code=400, detail=f"审批流校验失败: {'; '.join(errors)}")
    wf.name = payload.name
    wf.description = payload.description
    wf.order = payload.order
    save_graph(db, wf, payload.nodes, payload.edges)
    db.commit()
    db.refresh(wf)
    return _workflow_response(db, wf)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除审批流（admin 及以上；绑定的表单由 FK SET NULL 自动解绑）."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_admin(db, ws, current_user)
    wf = db.get(Workflow, workflow_id)
    if wf is None or wf.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="审批流不存在")
    db.delete(wf)
    db.commit()


__all__ = ["router"]

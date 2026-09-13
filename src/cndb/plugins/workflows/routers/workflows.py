"""工作流管理路由 — 编排导航型：节点绑定数据表，边表达流程顺序.

端点总览（挂载于 /api/v1/workspaces/{workspace_id}/workflows）：
- GET    ""                       工作流列表（含节点数）
- POST   ""                       创建工作流（EDITOR）
- GET    "/{workflow_id}"         详情（节点含绑定表摘要 + 边）
- PATCH  "/{workflow_id}"         更新名称/描述/排序（EDITOR）
- DELETE "/{workflow_id}"         删除工作流（ADMIN）
- POST   "/{workflow_id}/nodes"   添加节点（EDITOR）
- PATCH  "/{workflow_id}/nodes/{node_id}"   更新节点（EDITOR）
- DELETE "/{workflow_id}/nodes/{node_id}"   删除节点（边级联，EDITOR）
- POST   "/{workflow_id}/edges"   添加边（EDITOR）
- PATCH  "/{workflow_id}/edges/{edge_id}"   更新边标签（EDITOR）
- DELETE "/{workflow_id}/edges/{edge_id}"   删除边（EDITOR）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.graph import count_physical_rows
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.workflows.models import Workflow, WorkflowEdge, WorkflowNode
from cndb.plugins.workflows.schemas import (
    EdgeCreate,
    EdgeUpdate,
    NodeCreate,
    NodeTableBrief,
    NodeUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}/workflows", tags=["workflows"])


# ── 权限辅助 ─────────────────────────────────────────


def _check_workspace_permission(workspace_id: int, user: User, db: Session, min_role: WorkspaceRole) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")
    return ws


def _get_workflow_or_404(workflow_id: int, workspace_id: int, db: Session) -> Workflow:
    wf = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id).first()
    if wf is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return wf


def _validate_table_binding(workspace_id: int, table_id: int | None, db: Session) -> None:
    """校验节点绑定的表存在、未软删且属于同一工作区."""
    if table_id is None:
        return
    dt = db.query(DataTable).filter(DataTable.id == table_id).first()
    if dt is None or dt.trashed:
        raise HTTPException(status_code=400, detail="绑定表不存在或已删除")
    if dt.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="不能绑定其他工作区的表")


# ── 绑定表摘要 ───────────────────────────────────────


def _table_briefs(wf: Workflow, db: Session) -> dict[int, NodeTableBrief]:
    """批量构建 {table_id: 摘要}；表软删/移出工作区时跳过（前端显示未绑定）."""
    engine = db.get_bind()
    table_ids = {n.table_id for n in wf.nodes if n.table_id is not None}
    if not table_ids:
        return {}

    tables = db.query(DataTable).filter(DataTable.id.in_(table_ids)).all()
    _rows = (
        db.query(DataView.table_id, func.count(DataView.id))
        .filter(DataView.table_id.in_(table_ids))
        .group_by(DataView.table_id)
        .all()
    )
    view_counts: dict[int, int] = {int(r[0]): int(r[1]) for r in _rows}

    briefs: dict[int, NodeTableBrief] = {}
    for dt in tables:
        if dt.trashed or dt.workspace_id != wf.workspace_id:
            continue
        briefs[dt.id] = NodeTableBrief(
            id=dt.id,
            name=dt.name,
            view_count=view_counts.get(dt.id, 0),
            row_count=count_physical_rows(engine, dt),
        )
    return briefs


def _single_table_brief(db: Session, workspace_id: int, table_id: int) -> dict[str, Any] | None:
    """单张表的摘要（用于 create_node/update_node 即时返回）.

    找不到 / 已软删 / 不属于该工作区时返回 None.
    """
    dt = db.query(DataTable).filter(DataTable.id == table_id).first()
    if dt is None or dt.trashed or dt.workspace_id != workspace_id:
        return None
    engine = db.get_bind()
    _views = db.query(func.count(DataView.id)).filter(DataView.table_id == table_id).scalar() or 0
    return {
        "id": dt.id,
        "name": dt.name,
        "view_count": int(_views),
        "row_count": count_physical_rows(engine, dt),
    }


# ── Workflow CRUD ────────────────────────────────────


@router.get("", response_model=list[dict[str, object]])
def list_workflows(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    wfs = db.query(Workflow).filter(Workflow.workspace_id == workspace_id).order_by(Workflow.order, Workflow.id).all()
    counts = dict(
        db.query(WorkflowNode.workflow_id, func.count(WorkflowNode.id))
        .filter(WorkflowNode.workflow_id.in_([w.id for w in wfs] or [0]))
        .group_by(WorkflowNode.workflow_id)
        .all()
    )
    return [
        {
            "id": w.id,
            "workspace_id": w.workspace_id,
            "name": w.name,
            "description": w.description,
            "order": w.order,
            "node_count": counts.get(w.id, 0),
            "created_at": w.created_at,
            "updated_at": w.updated_at,
        }
        for w in wfs
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workflow(
    workspace_id: int,
    payload: WorkflowCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="工作流名称不能为空")
    wf = Workflow(workspace_id=workspace_id, name=payload.name.strip(), description=payload.description)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return {
        "id": wf.id,
        "workspace_id": wf.workspace_id,
        "name": wf.name,
        "description": wf.description,
        "order": wf.order,
        "node_count": 0,
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


@router.get("/{workflow_id}")
def get_workflow(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)

    briefs = _table_briefs(wf, db)
    nodes = []
    for n in wf.nodes:
        brief = briefs.get(n.table_id) if n.table_id is not None else None
        nodes.append(
            {
                "id": n.id,
                "workflow_id": n.workflow_id,
                "name": n.name,
                "table_id": n.table_id,
                "pos_x": n.pos_x,
                "pos_y": n.pos_y,
                "config": n.config or {},
                "table": (
                    {"id": brief.id, "name": brief.name, "view_count": brief.view_count, "row_count": brief.row_count}
                    if brief
                    else None
                ),
                "created_at": n.created_at,
                "updated_at": n.updated_at,
            }
        )
    edges = [
        {
            "id": e.id,
            "workflow_id": e.workflow_id,
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "label": e.label,
            "created_at": e.created_at,
            "updated_at": e.updated_at,
        }
        for e in wf.edges
    ]
    return {
        "id": wf.id,
        "workspace_id": wf.workspace_id,
        "name": wf.name,
        "description": wf.description,
        "order": wf.order,
        "node_count": len(nodes),
        "nodes": nodes,
        "edges": edges,
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


@router.patch("/{workflow_id}")
def update_workflow(
    workspace_id: int,
    workflow_id: int,
    payload: WorkflowUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and not str(update_data["name"]).strip():
        raise HTTPException(status_code=400, detail="工作流名称不能为空")
    for key, value in update_data.items():
        setattr(wf, key, value)
    db.commit()
    db.refresh(wf)
    return {
        "id": wf.id,
        "workspace_id": wf.workspace_id,
        "name": wf.name,
        "description": wf.description,
        "order": wf.order,
        "node_count": len(wf.nodes),
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)
    db.delete(wf)
    db.commit()


# ── Node 管理 ────────────────────────────────────────


@router.post("/{workflow_id}/nodes", status_code=status.HTTP_201_CREATED)
def create_node(
    workspace_id: int,
    workflow_id: int,
    payload: NodeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)
    _validate_table_binding(workspace_id, payload.table_id, db)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="节点名称不能为空")

    node = WorkflowNode(
        workflow_id=wf.id,
        name=payload.name.strip(),
        table_id=payload.table_id,
        pos_x=payload.pos_x,
        pos_y=payload.pos_y,
        config=payload.config,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    brief = _single_table_brief(db, workspace_id, node.table_id) if node.table_id is not None else None
    return {
        "id": node.id,
        "workflow_id": node.workflow_id,
        "name": node.name,
        "table_id": node.table_id,
        "pos_x": node.pos_x,
        "pos_y": node.pos_y,
        "config": node.config or {},
        "table": brief,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


@router.patch("/{workflow_id}/nodes/{node_id}")
def update_node(
    workspace_id: int,
    workflow_id: int,
    node_id: int,
    payload: NodeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)
    node = db.query(WorkflowNode).filter(WorkflowNode.id == node_id, WorkflowNode.workflow_id == wf.id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="节点不存在")

    update_data = payload.model_dump(exclude_unset=True)
    if "table_id" in update_data:
        _validate_table_binding(workspace_id, update_data["table_id"], db)
    if "name" in update_data and not str(update_data["name"]).strip():
        raise HTTPException(status_code=400, detail="节点名称不能为空")
    for key, value in update_data.items():
        setattr(node, key, value)
    db.commit()
    db.refresh(node)
    brief = _single_table_brief(db, workspace_id, node.table_id) if node.table_id is not None else None
    return {
        "id": node.id,
        "workflow_id": node.workflow_id,
        "name": node.name,
        "table_id": node.table_id,
        "pos_x": node.pos_x,
        "pos_y": node.pos_y,
        "config": node.config or {},
        "table": brief,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


@router.delete("/{workflow_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    workspace_id: int,
    workflow_id: int,
    node_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)
    node = db.query(WorkflowNode).filter(WorkflowNode.id == node_id, WorkflowNode.workflow_id == wf.id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    # SQLite 默认关闭 FK 约束，手动清理关联边
    db.query(WorkflowEdge).filter(
        WorkflowEdge.source_node_id == node_id,
    ).delete()
    db.query(WorkflowEdge).filter(
        WorkflowEdge.target_node_id == node_id,
    ).delete()
    db.delete(node)
    db.commit()


# ── Edge 管理 ────────────────────────────────────────


@router.post("/{workflow_id}/edges", status_code=status.HTTP_201_CREATED)
def create_edge(
    workspace_id: int,
    workflow_id: int,
    payload: EdgeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)

    node_ids = {n.id for n in wf.nodes}
    if payload.source_node_id not in node_ids or payload.target_node_id not in node_ids:
        raise HTTPException(status_code=400, detail="边端点必须属于该工作流")
    if payload.source_node_id == payload.target_node_id:
        raise HTTPException(status_code=400, detail="不允许自环边")
    dup = (
        db.query(WorkflowEdge)
        .filter(
            WorkflowEdge.workflow_id == wf.id,
            WorkflowEdge.source_node_id == payload.source_node_id,
            WorkflowEdge.target_node_id == payload.target_node_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="边已存在")

    edge = WorkflowEdge(
        workflow_id=wf.id,
        source_node_id=payload.source_node_id,
        target_node_id=payload.target_node_id,
        label=payload.label,
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return {
        "id": edge.id,
        "workflow_id": edge.workflow_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "label": edge.label,
        "created_at": edge.created_at,
        "updated_at": edge.updated_at,
    }


@router.patch("/{workflow_id}/edges/{edge_id}")
def update_edge(
    workspace_id: int,
    workflow_id: int,
    edge_id: int,
    payload: EdgeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)
    edge = db.query(WorkflowEdge).filter(WorkflowEdge.id == edge_id, WorkflowEdge.workflow_id == wf.id).first()
    if edge is None:
        raise HTTPException(status_code=404, detail="边不存在")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(edge, key, value)
    db.commit()
    db.refresh(edge)
    return {
        "id": edge.id,
        "workflow_id": edge.workflow_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "label": edge.label,
        "created_at": edge.created_at,
        "updated_at": edge.updated_at,
    }


@router.delete("/{workflow_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge(
    workspace_id: int,
    workflow_id: int,
    edge_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    wf = _get_workflow_or_404(workflow_id, workspace_id, db)
    edge = db.query(WorkflowEdge).filter(WorkflowEdge.id == edge_id, WorkflowEdge.workflow_id == wf.id).first()
    if edge is None:
        raise HTTPException(status_code=404, detail="边不存在")
    db.delete(edge)
    db.commit()


__all__ = ["router"]

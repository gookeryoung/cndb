"""表关系图 API 路由.

提供两个端点：
- GET /{workspace_id}/graph          — 工作区关系图（节点 + 边 + 拓扑序）
- GET /{workspace_id}/dependencies   — 工作区依赖详情（前向 + 反向 + link 字段列表）

节点字段对齐前端 GraphNode 契约：id(str)/label/type + 统计要素(field_count/row_count/view_count/link_count)
边字段对齐前端 GraphEdge 契约：source(str)/target(str)/label + link_field_name(兼容保留)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.graph import (
    build_table_graph,
    count_physical_rows,
    get_workspace_dependencies,
    topological_sort,
)
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}", tags=["graph"])


def _check_workspace_permission(workspace_id: int, user: User, db: Session, min_role: WorkspaceRole) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")
    return ws


@router.get("/graph")
def get_workspace_graph(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """返回工作区内所有表的 link 字段关系图 + 拓扑序.

    节点统计要素：field_count / row_count / view_count / link_count(入度)
    """
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    tables = db.query(DataTable).filter(DataTable.workspace_id == workspace_id, DataTable.trashed.is_(False)).all()

    # 批量统计：视图数 + link 字段数
    table_ids = [t.id for t in tables]
    _views = (
        db.query(DataView.table_id, func.count(DataView.id))
        .filter(DataView.table_id.in_(table_ids))
        .group_by(DataView.table_id)
        .all()
    )
    view_counts: dict[int, int] = {int(r[0]): int(r[1]) for r in _views}

    engine = db.get_bind()

    # 构建边（收集 link 字段），同时统计每张表的 link_count
    table_map = {t.id: t for t in tables}
    link_count: dict[int, int] = {t.id: 0 for t in tables}
    edges: list[dict[str, Any]] = []

    for t in tables:
        for f in t.fields:
            if f.trashed or f.field_type != "link":
                continue
            target_tid = f.config.get("target_table_id") if f.config else None
            if target_tid is not None and target_tid in table_map:
                # 被引用表入度 +1
                link_count[target_tid] = link_count.get(target_tid, 0) + 1
                edges.append(
                    {
                        "source": str(t.id),
                        "target": str(target_tid),
                        "label": f.name,
                        "link_field_name": f.name,
                    }
                )

    # 构建节点（对齐前端契约 id/label/type + 统计要素）
    nodes: list[dict[str, Any]] = []
    for t in tables:
        active_fields = [f for f in t.fields if not f.trashed]
        nodes.append(
            {
                "id": str(t.id),
                "label": t.name,
                "type": "table",
                "table_id": t.id,
                "name": t.name,
                "field_count": len(active_fields),
                "row_count": count_physical_rows(engine, t),
                "view_count": view_counts.get(t.id, 0),
                "link_count": link_count.get(t.id, 0),
                "trashed": t.trashed,
            }
        )

    # 拓扑排序（保持 int → 转 str 对齐前端）
    graph = build_table_graph(db, workspace_id)
    topo_order_int = topological_sort(graph)
    topo_order = [str(tid) for tid in topo_order_int]

    return {
        "nodes": nodes,
        "edges": edges,
        "topo_order": topo_order,
    }


@router.get("/dependencies")
def get_dependencies(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """返回工作区依赖详情."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    return get_workspace_dependencies(db, workspace_id)


__all__ = ["router"]

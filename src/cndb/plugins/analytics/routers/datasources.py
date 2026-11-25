"""分析数据源清单（ADR 0158 P0）：本工作区表 + 我可见的工作区链接.

链接项只列「生效中」的（未过期 / 已批准），并标注 `readable`（当前用户在源工作区
是否有 READ）。不可读的链接仍列出（便于解释「为什么选不了」），但不参与执行。
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.schemas import AnalyticsDatasourceItem, AnalyticsDatasourcesResponse
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import Workspace, WorkspaceLink, WorkspaceLinkStatus, WorkspaceRole
from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities
from cndb.plugins.workspaces.services.links import _as_utc, is_expired

router = APIRouter(prefix="/{workspace_id}/analytics", tags=["analytics"])


@router.get("/datasources", response_model=AnalyticsDatasourcesResponse)
def list_datasources(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsDatasourcesResponse:
    """分析页可选数据源：本工作区表 + 我可见的工作区链接（ADR 0158 C1/C5）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)

    tables = (
        db.query(DataTable)
        .filter(DataTable.workspace_id == workspace_id, DataTable.trashed_at.is_(None))
        .order_by(DataTable.order, DataTable.id)
        .all()
    )
    table_items = [
        AnalyticsDatasourceItem(type="table", id=table.id, name=table.name, readable=True) for table in tables
    ]

    now = dt.datetime.now(dt.UTC)
    links = (
        db.query(WorkspaceLink)
        .filter(
            WorkspaceLink.workspace_id == workspace_id,
            WorkspaceLink.status == WorkspaceLinkStatus.ACTIVE,
        )
        .order_by(WorkspaceLink.id.desc())
        .all()
    )
    link_items: list[AnalyticsDatasourceItem] = []
    for link in links:
        if is_expired(link, now=now):
            continue
        source = db.get(Workspace, link.source_workspace_id)
        readable = bool(
            source is not None and resolve_capabilities(current_user, source, db).allows(WorkspaceCapability.READ)
        )
        link_items.append(
            AnalyticsDatasourceItem(
                type="link",
                id=link.id,
                link_id=link.id,
                name=link.alias,
                source_workspace_name=source.name if source is not None else None,
                expires_at=_as_utc(link.expires_at),
                readable=readable,
            )
        )
    return AnalyticsDatasourcesResponse(tables=table_items, links=link_items)


__all__ = ["router"]

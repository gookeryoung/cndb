"""工作区统一检索路由 —— 顶栏搜索框的数据源.

GET /search —— 文档全文（FTS5）+ 数据表（表名 / 行），按 scope 分组返回。
数据表侧默认只在「当前激活视图」的范围内检索（见 services/search.py）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/workspaces/{workspace_id}/search", tags=["search"])


@router.get("")
def search(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=1, max_length=200, description="关键词"),
    scope: str = Query(default="all", pattern="^(all|documents|tables)$", description="检索范围"),
    table_id: int | None = Query(default=None, description="当前激活的表（数据表侧收敛到该表）"),
    view_id: int | None = Query(default=None, description="当前激活的视图（数据表侧按其筛选范围检索）"),
    limit: int = Query(default=10, ge=1, le=30),
) -> dict[str, Any]:
    """工作区统一检索（成员可见，结果按权限裁剪）."""
    from cndb.plugins.workspaces.services.search import search_workspace

    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    keyword = q.strip()
    if not keyword:
        return {"query": "", "documents": [], "tables": [], "rows": [], "view": None}
    return search_workspace(
        db,
        workspace_id,
        current_user,
        keyword,
        scope=scope,
        table_id=table_id,
        view_id=view_id,
        limit=limit,
    )

"""工作区统一检索路由 —— 顶栏搜索框的数据源.

GET /search —— 文档全文（FTS5）+ 数据表（表名 / 行），按 scope 分组返回。
数据表侧：工作区范围覆盖全部可读表（不按视图收敛），数据表范围才收敛当前表 + 激活视图（见 services/search.py）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.services import gateway as llm_gateway
from cndb.plugins.llm.services.errors import LlmError
from cndb.plugins.llm.services.gateway import LlmContext
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole
from cndb.plugins.workspaces.services import ai as search_ai

router = APIRouter(prefix="/workspaces/{workspace_id}/search", tags=["search"])


@router.get("")
def search(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=1, max_length=200, description="关键词"),
    scope: str = Query(default="all", pattern="^(all|documents|tables)$", description="检索范围"),
    table_id: int | None = Query(
        default=None, description="当前激活的表（数据表范围收敛到该表；工作区范围仅排序优先）"
    ),
    view_id: int | None = Query(default=None, description="当前激活的视图（仅数据表范围生效，按该视图筛选范围检索）"),
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


class RewriteQueryRequest(BaseModel):
    """搜索意图改写请求."""

    query: str = Field(min_length=1, max_length=200, description="用户原始查询")


@router.post("/ai/rewrite")
def rewrite_query(
    workspace_id: int,
    payload: RewriteQueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """AI 改写搜索查询（失败回退原查询，保证搜索始终可用）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    original = payload.query.strip()
    if not original:
        return {"query": "", "rewritten": False}
    try:
        result = llm_gateway.invoke(
            db,
            current_user,
            search_ai.REWRITE_QUERY,
            user_content=f"用户查询：{original}",
            context=LlmContext(workspace_id=workspace_id, target_type="workspace", target_id=workspace_id),
        )
    except LlmError as exc:
        # 未配置 Key / 上游失败时不阻断搜索：回退原查询并带回可展示原因
        return {"query": original, "rewritten": False, "reason": str(exc)[:200]}
    rewritten = result.parsed.query.strip()[: search_ai.MAX_REWRITTEN_QUERY]
    if not rewritten:
        return {"query": original, "rewritten": False}
    return {"query": rewritten, "rewritten": rewritten != original}


__all__ = ["RewriteQueryRequest", "router"]

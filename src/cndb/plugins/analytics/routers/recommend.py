"""analytics 推荐路由：字段画像与智能推荐.

端点（前缀 /{workspace_id}/analytics）：
- GET "/recommendations?table_id={id}"  按数据表返回字段画像、推荐公式 /
  图表 / 分组汇总与典型示例（工作区 viewer + 表 READ 权限）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.analytics import services
from cndb.plugins.analytics.schemas import RecommendationsResponse
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_workspace_permission,
    get_table_or_404,
)
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/analytics", tags=["analytics"])


@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    table_id: int | None = None,
    link_id: int | None = None,
) -> dict[str, Any]:
    """返回数据源的字段画像与推荐配置（ADR 0158 P1：支持工作区链接）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    if table_id is None and link_id is None:
        # 存量口径：缺数据源参数按 FastAPI 校验错误处理（422），不改旧契约（ADR 0158 L6）
        raise HTTPException(status_code=422, detail="请指定 table_id 或 link_id")
    if table_id is not None and link_id is not None:
        raise HTTPException(status_code=400, detail="只允许单一数据源：不要同时传 table_id 与 link_id")

    if link_id is not None:
        from cndb.plugins.workspaces.services.links import link_query, resolve_link

        resolved = resolve_link(db, current_user, workspace_id=workspace_id, link_id=link_id)
        view_filters, _sorts, view_logic = link_query(resolved)
        return services.recommend.build_recommendations(
            db,
            resolved.table,
            current_user,
            filters=view_filters,
            filter_logic=view_logic,
        )

    if table_id is None:  # pragma: no cover - 上面已排除 both-None 与 both-given
        raise HTTPException(status_code=422, detail="请指定 table_id 或 link_id")
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    return services.recommend.build_recommendations(db, table, current_user)


__all__ = ["router"]

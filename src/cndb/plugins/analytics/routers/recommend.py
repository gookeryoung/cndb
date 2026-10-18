"""analytics 推荐路由：字段画像与智能推荐.

端点（前缀 /{workspace_id}/analytics）：
- GET "/recommendations?table_id={id}"  按数据表返回字段画像、推荐公式 /
  图表 / 分组汇总与典型示例（工作区 viewer + 表 READ 权限）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
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
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """返回数据表的字段画像与推荐配置（工作区 viewer + 表 READ 权限）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    return services.recommend.build_recommendations(db, table, current_user)


__all__ = ["router"]

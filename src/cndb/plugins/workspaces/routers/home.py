"""主页聚合路由（ADR 0160 P2）—— 跨工作区只读待办计数.

`GET /api/v1/home/summary`：登录即可用，无工作区参数；逐工作区复用既有判定
（`readable_tables` / `can_write_directly` / `MANAGE_LINKS`），只回聚合计数，
不含工作区 id / 名称 / 条目标题 / 行数据（ADR 0160 I1-I3）。

单独成 router（前缀 `/home`）而不是并入 `/workspaces`：主页语义是跨工作区聚合，
与单个工作区资源无关；也避免 `/workspaces/{workspace_id}` 吞掉这类路径。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.services.home_summary import cached_home_summary

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/summary")
def home_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """主页待办聚合：工作区 / 团队数 + 待办计数（只读，缓存 20s）.

    待办口径（ADR 0160 D3）：
    - `change_requests`：我能审的表上 open 且非本人提交；
    - `issues`：我可读表上的 open；
    - `link_requests`：我有 `MANAGE_LINKS` 的工作区里待审链接。

    `partial=True` 表示至少一个工作区统计失败并已降级为 0（HTTP 仍 200，ADR 0160 I5）。
    """
    return cached_home_summary(db, current_user)

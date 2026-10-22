"""能力目录（只读）：``GET /api/v1/llm/actions``（ADR 0020 P0）.

只返回已注册动作的元数据，供前端决定入口显隐；**不提供执行端点**（D5）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from cndb.api.deps import get_current_user
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.services.actions import catalog

router = APIRouter(prefix="/actions", tags=["llm"])


@router.get("")
def list_actions(current_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """已注册 AI 动作目录."""
    del current_user  # 登录即可读；目录不含用户数据
    return {"items": catalog()}


__all__ = ["router"]

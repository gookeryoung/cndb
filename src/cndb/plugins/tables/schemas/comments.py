"""评论/审计路由的 Pydantic schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    """发表评论请求."""

    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: int | None = None


class CommentUpdate(BaseModel):
    """更新评论请求."""

    content: str = Field(..., min_length=1, max_length=5000)


class CommentResponse(BaseModel):
    """评论响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_id: int
    row_id: int
    user_id: int
    content: str
    parent_id: int | None = None
    created_at: datetime | None = None


class AuditLogResponse(BaseModel):
    """审计日志响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_id: int
    action: str
    actor_id: int | None = None
    target_id: int | None = None
    detail: dict[str, Any]
    created_at: datetime | None = None


__all__ = [
    "AuditLogResponse",
    "CommentCreate",
    "CommentResponse",
    "CommentUpdate",
]

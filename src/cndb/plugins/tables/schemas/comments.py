"""审计路由的 Pydantic schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
]

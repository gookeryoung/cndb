"""站内通知 API（用户级）.

- GET  /api/v1/accounts/notifications            列表（倒序，含未读数，可按未读过滤/翻页）
- POST /api/v1/accounts/notifications/{id}/read  标记单条已读（仅本人）
- POST /api/v1/accounts/notifications/read-all   全部标记已读

只返回**当前用户**的通知；不做工作区维度过滤（通知天然按接收者隔离）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.accounts.services import notifications as notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    unread_only: Annotated[bool, Query(description="只看未读")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before_id: Annotated[int | None, Query(description="翻页：只返回 id 小于该值的通知")] = None,
) -> dict[str, Any]:
    """当前用户的通知列表 + 未读数."""
    return notification_service.list_notifications(
        db, current_user, unread_only=unread_only, limit=limit, before_id=before_id
    )


@router.post("/read-all")
def mark_all_read(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """全部标记已读，返回影响条数."""
    return {"updated": notification_service.mark_all_read(db, current_user)}


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    notification_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """标记单条已读（非本人或不存在 → 404，不泄露存在性）."""
    if not notification_service.mark_read(db, current_user, notification_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")


__all__ = ["router"]

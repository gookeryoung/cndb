"""站内通知服务：写入 + 查询 + 已读.

通知写入一律**尽力而为**（与审计一致）：失败不应影响主业务动作（例如授权本身）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import (
    NOTIFICATION_DOCUMENT_COLLABORATOR_ADDED,
    Notification,
    User,
)


def notify_document_collaborator_added(
    db: Session,
    *,
    actor: User | None,
    target_user_id: int,
    document_id: int,
    workspace_id: int,
    document_title: str,
    role: str,
) -> Notification | None:
    """写入「你被加入文档协作者」通知（best-effort，不抛异常）."""
    try:
        row = Notification(
            recipient_id=target_user_id,
            type=NOTIFICATION_DOCUMENT_COLLABORATOR_ADDED,
            actor_id=actor.id if actor is not None else None,
            workspace_id=workspace_id,
            document_id=document_id,
            payload={
                "document_title": document_title,
                "role": role,
                "actor_name": (actor.nickname or actor.username) if actor is not None else "",
            },
        )
        db.add(row)
        db.commit()
        return row
    except Exception:  # pragma: no cover - 通知失败不影响授权
        db.rollback()
        return None


def _serialize(db: Session, row: Notification) -> dict[str, Any]:
    actor_name = row.payload.get("actor_name") if row.payload else ""
    if not actor_name and row.actor_id is not None:
        actor = db.get(User, row.actor_id)
        if actor is not None:
            actor_name = actor.nickname or actor.username
    return {
        "id": row.id,
        "type": row.type,
        "actor_id": row.actor_id,
        "actor_name": actor_name,
        "workspace_id": row.workspace_id,
        "document_id": row.document_id,
        "document_title": (row.payload or {}).get("document_title", ""),
        "role": (row.payload or {}).get("role", ""),
        "read": row.read_at is not None,
        "created_at": row.created_at,
    }


def list_notifications(
    db: Session,
    user: User,
    *,
    unread_only: bool = False,
    limit: int = 20,
    before_id: int | None = None,
) -> dict[str, Any]:
    """当前用户的通知（倒序）+ 未读数."""
    stmt = select(Notification).where(Notification.recipient_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before_id is not None:
        stmt = stmt.where(Notification.id < before_id)
    rows = list(db.scalars(stmt.order_by(Notification.id.desc()).limit(limit)).all())
    unread = db.scalar(
        select(func.count(Notification.id)).where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
    )
    return {"items": [_serialize(db, r) for r in rows], "unread_count": int(unread or 0)}


def unread_count(db: Session, user: User) -> int:
    return int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == user.id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


def mark_read(db: Session, user: User, notification_id: int) -> bool:
    """把单条通知标记为已读（仅本人，幂等）."""
    row = db.get(Notification, notification_id)
    if row is None or row.recipient_id != user.id:
        return False
    if row.read_at is None:
        import datetime as dt

        row.read_at = dt.datetime.now(dt.UTC)
        db.commit()
    return True


def mark_all_read(db: Session, user: User) -> int:
    """把当前用户全部未读标记为已读，返回影响条数."""
    import datetime as dt

    result = db.execute(
        update(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
        .values(read_at=dt.datetime.now(dt.UTC))
    )
    db.commit()
    # Result typing 不保证 rowcount（CursorResult 才有）：运行期取不到时按 0 处理
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "notify_document_collaborator_added",
    "unread_count",
]

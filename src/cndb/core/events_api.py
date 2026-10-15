"""统一事件流查询路由（``/api/v1/admin/events``）.

权限与既有审计日志一致：超级管理员或审计管理员可读（``users.py::_require_audit_reader`` 同口径）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.events import distinct_actions, query_events

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _require_audit_reader(current_user: object = Depends(get_current_user)) -> Any:
    """读事件流需要登录且为超级管理员或审计管理员."""
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    is_super = bool(getattr(current_user, "is_superuser", False))
    role = getattr(current_user, "role", "")
    if not (is_super or role == "audit_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需超级管理员或审计管理员权限")
    return current_user


def _serialize(event: object) -> dict[str, Any]:
    """事件 → 响应体（时间统一 ISO 字符串）."""
    created = getattr(event, "created_at", None)
    return {
        "id": getattr(event, "id", None),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "action": getattr(event, "action", ""),
        "workspace_id": getattr(event, "workspace_id", None),
        "actor_id": getattr(event, "actor_id", None),
        "actor_name": getattr(event, "actor_name", None),
        "target_type": getattr(event, "target_type", ""),
        "target_id": getattr(event, "target_id", None),
        "summary": getattr(event, "summary", ""),
        "detail": getattr(event, "detail", {}) or {},
        "request_id": getattr(event, "request_id", None),
    }


@router.get("/events")
def list_events(
    _current_user: Annotated[Any, Depends(_require_audit_reader)],
    db: Annotated[Session, Depends(get_db)],
    action: str | None = Query(default=None, description="按动作精确筛选，如 auth.login"),
    actor_id: int | None = Query(default=None, description="按操作人筛选"),
    target_type: str | None = Query(default=None, description="目标类型：user/session/record/..."),
    target_id: str | None = Query(default=None, description="目标 id"),
    workspace_id: int | None = Query(default=None),
    request_id: str | None = Query(default=None, description="按 request_id 串联一次请求的全部事件"),
    keyword: str | None = Query(default=None, description="摘要 / 操作人关键词"),
    since: str | None = Query(default=None, description="起始时间（ISO）"),
    until: str | None = Query(default=None, description="结束时间（ISO）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """分页查询统一事件流（新事件在前）."""
    items, total = query_events(
        db,
        action=action,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        workspace_id=workspace_id,
        request_id=request_id,
        keyword=keyword,
        since=since,
        until=until,
        page=page,
        page_size=page_size,
    )
    return {"items": [_serialize(e) for e in items], "total": total, "page": page, "page_size": page_size}


@router.get("/events/actions")
def list_event_actions(
    _current_user: Annotated[Any, Depends(_require_audit_reader)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """列出出现过的动作与计数（供筛选下拉）."""
    return {"items": distinct_actions(db)}


def register_event_routes(app: Any) -> None:
    """挂载事件流路由（与 system 路由同一注册风格）."""
    app.include_router(router)


__all__ = ["register_event_routes", "router"]

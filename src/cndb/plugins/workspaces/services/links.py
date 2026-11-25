"""工作区链接服务（ADR 0154 P0）：申请校验、批量授予、撤回与到期清扫.

权限口径（L1）：链接**不授予**任何权限。A 期批准时把受众批量加为源工作区的真实
``WorkspaceMember(viewer)``，因此有效权限恒等于「用户在源工作区的既有角色」；
行级规则 / 字段隐藏 / 视图口径完全复用普通读路径（H15 / H17 不变）。
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from cndb.plugins.workspaces.models import (
    LINK_MAX_GRANTEES,
    LINK_TARGET_TABLE,
    LINK_TARGET_VALUES,
    LINK_TARGET_VIEW,
    Workspace,
    WorkspaceLink,
    WorkspaceLinkStatus,
    WorkspaceMember,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite 读回的时间可能没有 tz，统一按 UTC 解释（与 sync/cursor 同口径）."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def is_expired(link: WorkspaceLink, *, now: dt.datetime | None = None) -> bool:
    """链接是否已过期（L3：过期即入口失效，与成员行是否清扫无关）."""
    expires_at = _as_utc(link.expires_at)
    if expires_at is None:
        return False
    return (_as_utc(now) or _now()) >= expires_at


def link_is_readable(link: WorkspaceLink, *, now: dt.datetime | None = None) -> bool:
    """链接入口是否可用（active 且未过期）."""
    return link.status is WorkspaceLinkStatus.ACTIVE and not is_expired(link, now=now)


def validate_target(
    db: Session,
    *,
    source_workspace_id: int,
    target_table_id: int,
    target_view_id: int | None,
) -> tuple[Any, Any | None]:
    """校验目标表 / 视图属于源工作区且未软删；不满足抛 400 / 404.

    Returns:
        ``(table, view_or_none)``。
    """
    from cndb.plugins.tables.models import DataTable, DataView

    table = db.get(DataTable, target_table_id)
    if table is None or table.workspace_id != source_workspace_id or getattr(table, "trashed_at", None) is not None:
        raise HTTPException(status_code=404, detail="目标数据表不存在")
    if target_view_id is None:
        return table, None
    view = db.get(DataView, target_view_id)
    if view is None or view.table_id != table.id:
        raise HTTPException(status_code=400, detail="目标视图不属于该数据表")
    return table, view


def _invalidate_membership_caches(workspace_id: int) -> int:
    """成员变化后失效工作区列表 / 统计 / 检索缓存（与成员路由同口径）."""
    from cndb.core.cache import cache_key, list_cache, search_cache

    cleared = list_cache.clear(cache_key("ws-list"))
    cleared += list_cache.clear(cache_key("workspace-stats", workspace_id))
    cleared += search_cache.clear(cache_key("global-search"))
    cleared += search_cache.clear(cache_key("team-search"))
    return cleared


def expand_audience(db: Session, link: WorkspaceLink) -> list[int]:
    """展开受众 = 消费方工作区当前成员（A 期口径，ADR 0154 §4.3）."""
    rows = (
        db.query(WorkspaceMember.user_id)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(WorkspaceMember.workspace_id == link.workspace_id)
        .all()
    )
    return [int(row[0]) for row in rows]


def grant_viewer_members(db: Session, link: WorkspaceLink) -> tuple[list[int], list[int]]:
    """把受众批量加为源工作区 viewer（幂等：已是成员的不重复创建）.

    Returns:
        ``(granted_ids, created_ids)``：前者是本次受众全集，后者只含**由链接创建**的
        成员（撤回 / 过期只删这一份，L9）。
    """
    audience = expand_audience(db, link)
    if len(audience) > LINK_MAX_GRANTEES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"单条链接最多授予 {LINK_MAX_GRANTEES} 人，请改用团队授权",
        )
    existing = {
        int(row[0])
        for row in db.query(WorkspaceMember.user_id)
        .filter(
            WorkspaceMember.workspace_id == link.source_workspace_id,
            WorkspaceMember.user_id.in_(audience or [0]),
        )
        .all()
    }
    created: list[int] = []
    for user_id in audience:
        if user_id in existing:
            continue
        db.add(
            WorkspaceMember(
                workspace_id=link.source_workspace_id,
                user_id=user_id,
                role=WorkspaceRole.VIEWER,
            )
        )
        created.append(user_id)
    return audience, created


def revoke_created_members(db: Session, link: WorkspaceLink) -> int:
    """删除链接创建的成员（L9 / D9：只删 created_member_ids，且仅当角色仍是 viewer）."""
    ids = [int(x) for x in (link.created_member_ids or [])]
    if not ids:
        return 0
    rows = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == link.source_workspace_id,
            WorkspaceMember.user_id.in_(ids),
            WorkspaceMember.role == WorkspaceRole.VIEWER,
        )
        .all()
    )
    for row in rows:
        db.delete(row)
    link.created_member_ids = []
    return len(rows)


def link_payload(
    db: Session,
    link: WorkspaceLink,
    user: User,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """组装链接响应载荷（可解释性 L8）."""
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities

    source = db.get(Workspace, link.source_workspace_id)
    table = db.get(DataTable, link.target_table_id)
    approver = db.get(type(user), link.approved_by_id) if link.approved_by_id else None
    source_caps = resolve_capabilities(user, source, db) if source is not None else None
    return {
        "id": link.id,
        "workspace_id": link.workspace_id,
        "source_workspace_id": link.source_workspace_id,
        "source_workspace_name": source.name if source is not None else "",
        "target_type": link.target_type,
        "target_table_id": link.target_table_id,
        "target_table_name": table.name if table is not None else "",
        "target_view_id": link.target_view_id,
        "alias": link.alias,
        "status": link.status.value,
        "ttl_days": link.ttl_days,
        "expires_at": _as_utc(link.expires_at),
        "created_by_id": link.created_by_id,
        "approved_by_name": (approver.nickname or approver.username) if approver is not None else None,
        "approved_at": _as_utc(link.approved_at),
        "note": link.note or "",
        "readable": bool(
            link_is_readable(link, now=now) and source_caps is not None and source_caps.allows(WorkspaceCapability.READ)
        ),
        "created_at": link.created_at,
        "updated_at": link.updated_at,
    }


def sweep_expired_links(db: Session, *, now: dt.datetime | None = None, limit: int = 200) -> dict[str, Any]:
    """回收过期链接：删除其创建的成员行并置 ``expired``（ADR 0154 D10 / C10）.

    幂等：重复执行只剩「已过期且已无 created members」的链接会被跳过（状态已是 expired）。
    """
    from cndb.core.events import record_event

    now = _as_utc(now) or _now()
    rows = (
        db.query(WorkspaceLink)
        .filter(
            WorkspaceLink.status == WorkspaceLinkStatus.ACTIVE,
            WorkspaceLink.expires_at.is_not(None),
            WorkspaceLink.expires_at <= now,
        )
        .order_by(WorkspaceLink.id)
        .limit(limit)
        .all()
    )
    removed: list[dict[str, Any]] = []
    for link in rows:
        removed_count = revoke_created_members(db, link)
        link.status = WorkspaceLinkStatus.EXPIRED
        record_event(
            db,
            "workspace.link_expired",
            summary=f"链接「{link.alias}」到期，回收 {removed_count} 个只读成员",
            target_type="workspace",
            target_id=link.source_workspace_id,
            workspace_id=link.source_workspace_id,
            detail={"link_id": link.id, "removed_members": removed_count},
            commit=False,
        )
        removed.append({"link_id": link.id, "removed_members": removed_count})
    if rows:
        db.commit()
        for link in rows:
            _invalidate_membership_caches(link.source_workspace_id)
    return {"expired": len(rows), "details": removed}


__all__ = [
    "LINK_TARGET_TABLE",
    "LINK_TARGET_VALUES",
    "LINK_TARGET_VIEW",
    "expand_audience",
    "grant_viewer_members",
    "is_expired",
    "link_is_readable",
    "link_payload",
    "revoke_created_members",
    "sweep_expired_links",
    "validate_target",
]

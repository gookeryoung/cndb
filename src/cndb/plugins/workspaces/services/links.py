"""工作区链接服务（ADR 0154 P0）：申请校验、批量授予、撤回与到期清扫.

权限口径（L1）：链接**不授予**任何权限。A 期批准时把受众批量加为源工作区的真实
``WorkspaceMember(viewer)``，因此有效权限恒等于「用户在源工作区的既有角色」；
行级规则 / 字段隐藏 / 视图口径完全复用普通读路径（H15 / H17 不变）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from cndb.plugins.workspaces.models import (
    LINK_MAX_GRANTEES,
    LINK_TARGET_TABLE,
    LINK_TARGET_VALUES,
    LINK_TARGET_VIEW,
    TEAM_ACCESS_ROLE,
    Workspace,
    WorkspaceLink,
    WorkspaceLinkStatus,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceTeamAccess,
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


#: 由链接创建的团队授权用 note 打标（撤回时只删自己创建的那条，不影响独立授权）
TEAM_ACCESS_LINK_NOTE_PREFIX = "link:"


def link_note_marker(link_id: int) -> str:
    """团队授权的「由某条链接创建」标记（撤回 / 到期只删带此标记的行）."""
    return f"{TEAM_ACCESS_LINK_NOTE_PREFIX}{link_id}"


def grant_team_access(
    db: Session,
    *,
    workspace_id: int,
    team_id: int,
    expires_at: dt.datetime | None,
    granted_by_id: int | None,
    note: str = "",
    role: str | None = None,
) -> WorkspaceTeamAccess:
    """授 / 改「团队 = viewer / editor」（同 (工作区, 团队) 覆盖，不重复插行）（ADR 0163 D2）.

    ``role`` 为 ``None`` 时：新建行用默认 viewer，覆盖已有行**保持原 role 不变**——
    链接路径不传 role，避免把 owner 手工授的 editor 静默降级成 viewer（D3）。
    显式传 role（如路由层）则两分支都写入该值。
    """
    row = (
        db.query(WorkspaceTeamAccess)
        .filter(WorkspaceTeamAccess.workspace_id == workspace_id, WorkspaceTeamAccess.team_id == team_id)
        .first()
    )
    if row is None:
        row = WorkspaceTeamAccess(
            workspace_id=workspace_id,
            team_id=team_id,
            role=role or TEAM_ACCESS_ROLE,
            expires_at=expires_at,
            granted_by_id=granted_by_id,
            note=note,
        )
        db.add(row)
    else:
        row.expires_at = expires_at
        row.granted_by_id = granted_by_id
        row.note = note
        if role is not None:
            row.role = role
    return row


def revoke_link_team_access(db: Session, link: WorkspaceLink) -> int:
    """撤回链接时回收**它创建**的团队授权（按 note 标记，不误删独立授权）."""
    if link.granted_team_id is None:
        return 0
    row = (
        db.query(WorkspaceTeamAccess)
        .filter(
            WorkspaceTeamAccess.workspace_id == link.source_workspace_id,
            WorkspaceTeamAccess.team_id == link.granted_team_id,
            WorkspaceTeamAccess.note == link_note_marker(link.id),
        )
        .first()
    )
    if row is None:
        return 0
    db.delete(row)
    return 1


def team_access_payload(db: Session, row: WorkspaceTeamAccess) -> dict[str, Any]:
    """团队授权响应载荷（带团队名与生效状态）."""
    from cndb.plugins.workspaces.models import Team

    team = db.get(Team, row.team_id)
    expires_at = _as_utc(row.expires_at)
    active = expires_at is None or expires_at > _now()
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "team_id": row.team_id,
        "team_name": team.name if team is not None else "",
        "role": row.role,
        "expires_at": expires_at,
        "active": active,
        "note": row.note or "",
        "granted_by_id": row.granted_by_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def link_payload(
    db: Session,
    link: WorkspaceLink,
    user: User,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """组装链接响应载荷（可解释性 L8）."""
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.models import Team
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities

    source = db.get(Workspace, link.source_workspace_id)
    table = db.get(DataTable, link.target_table_id)
    granted_team = db.get(Team, link.granted_team_id) if link.granted_team_id else None
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
        "audience": link.audience or "members",
        "granted_team_id": link.granted_team_id,
        "granted_team_name": granted_team.name if granted_team is not None else None,
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


@dataclass(frozen=True)
class ResolvedLink:
    """一次链接读取的解析结果（取数入口的唯一前置判定产物）."""

    link: WorkspaceLink
    table: Any
    view: Any
    source_workspace: Workspace


def resolve_link(
    db: Session,
    user: User,
    *,
    workspace_id: int,
    link_id: int,
) -> ResolvedLink:
    """解析链接并做取数前判定（ADR 0154 P1，L1/L3/L4）.

    失败口径：
    - 不存在 / 不属于该消费方工作区 / 未批准 / 已过期 / 目标表（视图）已删 → **404**；
    - 调用者对**源工作区**无 `READ`（或表级无 READ）→ **403**（文案指向源工作区拥有者）。

    判定后仍要求源工作区的数据面权限：A 期由「链接创建的 viewer 成员」满足，
    B′ 期由 `team_grant` 满足 —— 链接本身从不授予权限。
    """
    from cndb.plugins.tables.models import DataTable, DataView
    from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, raise_permission_denied, resolve_capabilities

    link = db.get(WorkspaceLink, link_id)
    if link is None or link.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="链接不存在")
    if not link_is_readable(link):
        raise HTTPException(status_code=404, detail="链接已失效")

    source = db.get(Workspace, link.source_workspace_id)
    if source is None:  # pragma: no cover - FK 级联保证存在
        raise HTTPException(status_code=404, detail="链接已失效")

    table = db.get(DataTable, link.target_table_id)
    if (
        table is None
        or table.workspace_id != source.id
        or getattr(table, "trashed_at", None) is not None
        or bool(getattr(table, "trashed", False))
    ):
        raise HTTPException(status_code=404, detail="链接已失效")

    view = None
    if link.target_view_id is not None:
        view = db.get(DataView, link.target_view_id)
        if view is None or view.table_id != table.id:
            raise HTTPException(status_code=404, detail="链接已失效")

    caps = resolve_capabilities(user, source, db)
    if not caps.allows(WorkspaceCapability.READ):
        raise_permission_denied(
            db,
            source,
            user,
            requirement="链接为只读引用，需你在源工作区具备读取权限",
        )
    # 表级 READ（含表成员 Role 的 READ 位）：与直接访问源表同一入口，不额外放宽
    get_table_or_404(table.id, source.id, db, user=user, action=TableAction.READ)
    return ResolvedLink(link=link, table=table, view=view, source_workspace=source)


def link_fields(db: Session, user: User, resolved: ResolvedLink) -> list[dict[str, Any]]:
    """链接可读字段（按字段隐藏裁剪，顺序与表一致）."""
    from cndb.plugins.tables.services.core.access import get_hidden_field_names
    from cndb.plugins.tables.services.core.field_serialization import field_response

    hidden = get_hidden_field_names(db, resolved.table, user)
    fields = sorted(
        (f for f in resolved.table.fields if not f.trashed),
        key=lambda f: (f.order, f.id),
    )
    return [field_response(field).model_dump() for field in fields if field.name not in hidden]


def link_query(resolved: ResolvedLink) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, str]:
    """链接默认查询条件：视图筛选 / 排序（无视图则无默认）.

    Returns:
        ``(filters, sorts, filter_logic)``，直接喂给 ``list_rows``。
    """
    if resolved.view is None:
        return None, None, "AND"
    filters = resolved.view.filters or None
    if isinstance(filters, dict):  # 历史数据可能是单对象
        filters = [filters]
    sorts = resolved.view.sortings or None
    logic = (resolved.view.filter_type or "AND").upper()
    return filters, sorts, logic


def link_rows(
    db: Session,
    user: User,
    resolved: ResolvedLink,
    *,
    filters: list[dict[str, Any]] | None = None,
    sorts: list[dict[str, Any]] | None = None,
    filter_logic: str = "AND",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """只读行查询：视图默认筛选 + 调用方筛选（AND 叠加），排序由调用方覆盖视图排序.

    取数复用 ``list_rows``：行级权限（ADR 0004）与字段隐藏在同一条路径生效，
    因此链接读不会越过 H15 / H17。
    """
    from cndb.plugins.tables.services.core.records import list_rows

    view_filters, view_sorts, view_logic = link_query(resolved)
    merged_filters = list(view_filters or []) + list(filters or [])
    merged_sorts = sorts if sorts else view_sorts
    logic = filter_logic if filters else view_logic

    try:
        rows, total = list_rows(
            db.get_bind(),
            resolved.table,
            filters=merged_filters or None,
            filter_logic=logic,
            sorts=merged_sorts,
            limit=limit,
            offset=offset,
            db=db,
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "link_id": resolved.link.id,
        "target_type": resolved.link.target_type,
    }


def link_export_csv(db: Session, user: User, resolved: ResolvedLink) -> str:
    """导出链接数据为 CSV（受同一行 / 列裁剪与 ``EXPORT_MAX_ROWS`` 上限，ADR 0148）."""
    from cndb.core.config import settings
    from cndb.plugins.tables.services.core.records import list_rows
    from cndb.plugins.tables.services.transfer.exporting import export_rows_to_csv

    view_filters, view_sorts, view_logic = link_query(resolved)
    cap = int(getattr(settings, "EXPORT_MAX_ROWS", 500_000))
    rows, total = list_rows(
        db.get_bind(),
        resolved.table,
        filters=view_filters,
        filter_logic=view_logic,
        sorts=view_sorts,
        limit=0,  # 不限数量：先 COUNT 再判上限（下面用 total 判定，避免全表载入）
        offset=0,
        db=db,
        user=user,
    )
    if total > cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前链接有 {total} 行，超过导出上限 {cap} 行（EXPORT_MAX_ROWS），请改用筛选条件分批导出",
        )
    columns = [field["name"] for field in link_fields(db, user, resolved)]
    return export_rows_to_csv(rows, columns=columns or None)


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
    "TEAM_ACCESS_LINK_NOTE_PREFIX",
    "ResolvedLink",
    "expand_audience",
    "grant_team_access",
    "grant_viewer_members",
    "is_expired",
    "link_export_csv",
    "link_fields",
    "link_is_readable",
    "link_note_marker",
    "link_payload",
    "link_query",
    "link_rows",
    "resolve_link",
    "revoke_created_members",
    "revoke_link_team_access",
    "sweep_expired_links",
    "team_access_payload",
    "validate_target",
]

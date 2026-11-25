"""工作区链接路由（ADR 0154 P0）：申请 / 列表 / 待批准 / 批准 / 拒绝 / 撤回.

只读引用通道（P1 才提供 fields / rows / export）。P0 的门控口径：

- 消费方发起 / 撤回：``EDIT_SETTINGS``（工作区所有者或团队管理员）；
- 源工作区批准 / 拒绝：``MANAGE_LINKS``（**仅源工作区所有者**，C2）；
- 列表：消费方成员（404 不泄露）。

链接**不授予**任何权限：批准时把受众批量加为源工作区真实 viewer（A 期，L1）。
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.events import record_event
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    LINK_DEFAULT_TTL_DAYS,
    LINK_MAX_TTL_DAYS,
    LINK_TARGET_TABLE,
    LINK_TARGET_VIEW,
    WorkspaceLink,
    WorkspaceLinkStatus,
)
from cndb.plugins.workspaces.permissions import WorkspaceCapability, require_capability, resolve_capabilities
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404, _require_member
from cndb.plugins.workspaces.schemas import (
    WorkspaceLinkApprove,
    WorkspaceLinkCreate,
    WorkspaceLinkResponse,
)
from cndb.plugins.workspaces.services.links import (
    grant_viewer_members,
    is_expired,
    link_export_csv,
    link_fields,
    link_payload,
    link_rows,
    resolve_link,
    revoke_created_members,
    validate_target,
)

router = APIRouter(prefix="/workspaces", tags=["workspace-links"])

#: 同一 (消费方, 源表, 视图) 只允许一条 active 链接（ADR 0154 §4.2）
_ACTIVE_DUPLICATE_DETAIL = "该表已存在生效中的链接，请先撤回或等待到期"


def _get_link_or_404(db: Session, link_id: int) -> WorkspaceLink:
    link = db.get(WorkspaceLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="链接不存在")
    return link


def _invalidate(workspace_id: int) -> None:
    """成员 / 链接变化后失效列表与检索引擎缓存（与成员路由同口径）."""
    from cndb.core.cache import cache_key, list_cache, search_cache

    list_cache.clear(cache_key("ws-list"))
    list_cache.clear(cache_key("workspace-stats", workspace_id))
    search_cache.clear(cache_key("global-search"))
    search_cache.clear(cache_key("team-search"))


def _event(
    db: Session,
    action: str,
    *,
    summary: str,
    workspace_id: int,
    user: User,
    detail: dict[str, Any] | None = None,
) -> None:
    record_event(
        db,
        action,
        summary=summary,
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=workspace_id,
        actor_id=user.id,
        actor_name=user.nickname or user.username,
        detail=detail or {},
        commit=False,
    )


def _default_alias(db: Session, workspace_id: int, table_name: str) -> str:
    """默认别名 = 表名；消费方内重名时追加 `-2` / `-3` …"""
    base = (table_name or "链接表")[:56]
    candidate = base
    suffix = 2
    while (
        db.query(WorkspaceLink.id)
        .filter(WorkspaceLink.workspace_id == workspace_id, WorkspaceLink.alias == candidate)
        .first()
        is not None
    ):
        candidate = f"{base}-{suffix}"[:64]
        suffix += 1
    return candidate


@router.post(
    "/{workspace_id}/links",
    response_model=WorkspaceLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_link(
    workspace_id: int,
    payload: WorkspaceLinkCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceLinkResponse:
    """发起跨工作区只读链接申请（消费方 `EDIT_SETTINGS`）."""
    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(
        WorkspaceCapability.EDIT_SETTINGS,
        db,
        ws,
        current_user,
        requirement="仅工作区所有者或团队管理员可发起链接申请",
    )
    if payload.source_workspace_id == workspace_id:
        raise HTTPException(status_code=400, detail="不能链接当前工作区自身")
    source = _get_workspace_or_404(payload.source_workspace_id, db)

    table, view = validate_target(
        db,
        source_workspace_id=source.id,
        target_table_id=payload.target_table_id,
        target_view_id=payload.target_view_id,
    )
    target_type = LINK_TARGET_VIEW if view is not None else LINK_TARGET_TABLE

    duplicate = (
        db.query(WorkspaceLink)
        .filter(
            WorkspaceLink.workspace_id == workspace_id,
            WorkspaceLink.source_workspace_id == source.id,
            WorkspaceLink.target_table_id == table.id,
            WorkspaceLink.status == WorkspaceLinkStatus.ACTIVE,
        )
        .first()
    )
    if duplicate is not None and not is_expired(duplicate):
        raise HTTPException(status_code=400, detail=_ACTIVE_DUPLICATE_DETAIL)

    alias = (payload.alias or "").strip() or _default_alias(db, workspace_id, table.name)
    if (
        db.query(WorkspaceLink.id)
        .filter(WorkspaceLink.workspace_id == workspace_id, WorkspaceLink.alias == alias)
        .first()
        is not None
    ):
        raise HTTPException(status_code=400, detail="该别名已被使用，请换一个")

    link = WorkspaceLink(
        workspace_id=workspace_id,
        source_workspace_id=source.id,
        target_type=target_type,
        target_table_id=table.id,
        target_view_id=view.id if view is not None else None,
        alias=alias,
        status=WorkspaceLinkStatus.PENDING,
        ttl_days=payload.ttl_days,
        granted_member_ids=[],
        created_member_ids=[],
        created_by_id=current_user.id,
        note=payload.note or "",
    )
    db.add(link)
    db.flush()
    _event(
        db,
        "workspace.link_request",
        summary=f"申请只读链接「{alias}」→ 工作区「{source.name}」的表「{table.name}」",
        workspace_id=workspace_id,
        user=current_user,
        detail={"link_id": link.id, "source_workspace_id": source.id, "target_table_id": table.id},
    )
    db.commit()
    db.refresh(link)
    return WorkspaceLinkResponse.model_validate(link_payload(db, link, current_user))


@router.get("/{workspace_id}/links", response_model=list[WorkspaceLinkResponse])
def list_links(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceLinkResponse]:
    """消费方链接列表（成员可读；非成员 404）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)
    rows = (
        db.query(WorkspaceLink)
        .filter(WorkspaceLink.workspace_id == workspace_id)
        .order_by(WorkspaceLink.id.desc())
        .all()
    )
    now = dt.datetime.now(dt.UTC)
    return [WorkspaceLinkResponse.model_validate(link_payload(db, link, current_user, now=now)) for link in rows]


# ── P1：只读引用（fields / rows / export；**不挂任何写方法**，ADR 0154 C4） ──


def _parse_json_list(raw: str | None) -> list[dict[str, Any]] | None:
    """解析前端传来的 filters / sorts（JSON 字符串，格式错→None 而非 400，与 records 同口径）."""
    import json

    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, list):
        return None
    items = [item for item in value if isinstance(item, dict)]
    return items or None


@router.get("/{workspace_id}/links/{link_id}/fields")
def get_link_fields(
    workspace_id: int,
    link_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """链接表的可读字段（按字段隐藏裁剪；不可读 → 404/403）."""
    resolved = resolve_link(db, current_user, workspace_id=workspace_id, link_id=link_id)
    return {
        "link_id": resolved.link.id,
        "table_id": resolved.table.id,
        "table_name": resolved.table.name,
        "target_type": resolved.link.target_type,
        "fields": link_fields(db, current_user, resolved),
    }


@router.get("/{workspace_id}/links/{link_id}/rows")
def get_link_rows(
    workspace_id: int,
    link_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: int = 0,
    limit: int = 50,
    filters: str | None = None,
    sorts: str | None = None,
    filter_logic: str = "AND",
) -> dict[str, Any]:
    """链接只读行（视图默认筛选 + 调用方筛选；分页上限 5000，与网格一致）."""
    if offset < 0 or limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="offset 需 ≥0，limit 需在 1–5000 之间")
    if filter_logic not in ("AND", "OR"):
        raise HTTPException(status_code=400, detail="filter_logic 只能是 AND / OR")
    resolved = resolve_link(db, current_user, workspace_id=workspace_id, link_id=link_id)
    return link_rows(
        db,
        current_user,
        resolved,
        filters=_parse_json_list(filters),
        sorts=_parse_json_list(sorts),
        filter_logic=filter_logic,
        limit=limit,
        offset=offset,
    )


@router.get("/{workspace_id}/links/{link_id}/export")
def export_link_csv(
    workspace_id: int,
    link_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """把链接数据导出为 CSV（同一行 / 列裁剪 + ``EXPORT_MAX_ROWS`` 上限）."""
    resolved = resolve_link(db, current_user, workspace_id=workspace_id, link_id=link_id)
    csv_text = link_export_csv(db, current_user, resolved)
    filename = f"{resolved.link.alias or resolved.table.name}.csv".replace("/", "_")
    return Response(
        content=csv_text.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/{workspace_id}/links/inbox", response_model=list[WorkspaceLinkResponse])
def list_link_inbox(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceLinkResponse]:
    """待本工作区批准的链接（源工作区所有者视角，`MANAGE_LINKS`）."""
    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(WorkspaceCapability.MANAGE_LINKS, db, ws, current_user, requirement="仅所有者可审批链接")
    rows = (
        db.query(WorkspaceLink)
        .filter(
            WorkspaceLink.source_workspace_id == workspace_id,
            WorkspaceLink.status == WorkspaceLinkStatus.PENDING,
        )
        .order_by(WorkspaceLink.id)
        .all()
    )
    return [WorkspaceLinkResponse.model_validate(link_payload(db, link, current_user)) for link in rows]


@router.post("/{workspace_id}/links/{link_id}/approve", response_model=WorkspaceLinkResponse)
def approve_link(
    workspace_id: int,
    link_id: int,
    payload: WorkspaceLinkApprove,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceLinkResponse:
    """批准链接（源工作区所有者）：批量授予 viewer 并写到期时间（C2 / A 期）."""
    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(WorkspaceCapability.MANAGE_LINKS, db, ws, current_user, requirement="仅所有者可批准链接")
    link = _get_link_or_404(db, link_id)
    if link.source_workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="链接不存在")
    if link.status is not WorkspaceLinkStatus.PENDING:
        raise HTTPException(status_code=400, detail="仅待批准的链接可以批准")

    ttl_days = payload.ttl_days or link.ttl_days or LINK_DEFAULT_TTL_DAYS
    if not 1 <= ttl_days <= LINK_MAX_TTL_DAYS:
        raise HTTPException(status_code=400, detail=f"有效期需在 1–{LINK_MAX_TTL_DAYS} 天之间")

    granted, created = grant_viewer_members(db, link)
    now = dt.datetime.now(dt.UTC)
    link.granted_member_ids = granted
    link.created_member_ids = created
    link.ttl_days = ttl_days
    link.expires_at = now + dt.timedelta(days=ttl_days)
    link.status = WorkspaceLinkStatus.ACTIVE
    link.approved_by_id = current_user.id
    link.approved_at = now
    _event(
        db,
        "workspace.link_approve",
        summary=f"批准只读链接「{link.alias}」：授予 {len(granted)} 人只读（新增 {len(created)} 人）",
        workspace_id=workspace_id,
        user=current_user,
        detail={
            "link_id": link.id,
            "granted": len(granted),
            "created": len(created),
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        },
    )
    db.commit()
    db.refresh(link)
    _invalidate(workspace_id)
    return WorkspaceLinkResponse.model_validate(link_payload(db, link, current_user))


@router.post("/{workspace_id}/links/{link_id}/reject", response_model=WorkspaceLinkResponse)
def reject_link(
    workspace_id: int,
    link_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceLinkResponse:
    """拒绝链接（源工作区所有者）."""
    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(WorkspaceCapability.MANAGE_LINKS, db, ws, current_user, requirement="仅所有者可拒绝链接")
    link = _get_link_or_404(db, link_id)
    if link.source_workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="链接不存在")
    if link.status is not WorkspaceLinkStatus.PENDING:
        raise HTTPException(status_code=400, detail="仅待批准的链接可以拒绝")
    link.status = WorkspaceLinkStatus.REJECTED
    _event(
        db,
        "workspace.link_reject",
        summary=f"拒绝只读链接「{link.alias}」",
        workspace_id=workspace_id,
        user=current_user,
        detail={"link_id": link.id},
    )
    db.commit()
    db.refresh(link)
    return WorkspaceLinkResponse.model_validate(link_payload(db, link, current_user))


@router.delete("/{workspace_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_link(
    workspace_id: int,
    link_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """撤回链接：消费方 `EDIT_SETTINGS` 或源工作区 `MANAGE_LINKS`；只删链接创建的成员（L9）."""
    ws = _get_workspace_or_404(workspace_id, db)
    link = _get_link_or_404(db, link_id)
    if workspace_id not in (link.workspace_id, link.source_workspace_id):
        raise HTTPException(status_code=404, detail="链接不存在")

    caps = resolve_capabilities(current_user, ws, db)
    if workspace_id == link.workspace_id:
        if not caps.allows(WorkspaceCapability.EDIT_SETTINGS):
            require_capability(
                WorkspaceCapability.EDIT_SETTINGS,
                db,
                ws,
                current_user,
                requirement="仅工作区所有者或团队管理员可撤回链接",
            )
    elif not caps.allows(WorkspaceCapability.MANAGE_LINKS):
        require_capability(WorkspaceCapability.MANAGE_LINKS, db, ws, current_user, requirement="仅所有者可撤回链接")

    removed = revoke_created_members(db, link)
    _event(
        db,
        "workspace.link_revoke",
        summary=f"撤回只读链接「{link.alias}」（回收 {removed} 个只读成员）",
        workspace_id=link.source_workspace_id,
        user=current_user,
        detail={"link_id": link.id, "removed_members": removed},
    )
    db.delete(link)
    db.commit()
    _invalidate(link.source_workspace_id)


__all__ = ["router"]

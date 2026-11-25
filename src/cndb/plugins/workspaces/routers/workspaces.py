"""workspaces 插件路由：CRUD + 成员管理 + pin + candidates."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    DEFAULT_STORAGE_QUOTA_BYTES,
    Team,
    TeamMember,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.modules import workspace_modules_from_meta
from cndb.plugins.workspaces.permissions import (
    WorkspaceCapability,
    require_capability,
    resolve_capabilities,
)
from cndb.plugins.workspaces.routers.deps import (
    _get_workspace_or_404,
    _require_member,
    _require_owner,
    _require_team_for_workspace,
    _require_workspace_owner,
)
from cndb.plugins.workspaces.routers.member_routes import router as member_router
from cndb.plugins.workspaces.schemas import (
    PinRequest,
    PinToggleResponse,
    WorkspaceArchiveInspectResponse,
    WorkspaceArchiveTarget,
    WorkspaceCapabilitiesResponse,
    WorkspaceContributionsResponse,
    WorkspaceCreate,
    WorkspaceCreateFromBackup,
    WorkspaceCreateFromBackupResponse,
    WorkspaceDetailResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
    WorkspaceWithPinnedResponse,
)
from cndb.plugins.workspaces.services.backup_io import (
    _coerce_row_value_types,
    import_backup_into_workspace,
)
from cndb.plugins.workspaces.services.teams import ensure_modules_allowed, team_policy_for

# 工作区列表缓存（进程内，短 TTL；写路径主动失效）
WORKSPACE_LIST_TTL_SECONDS = 10.0


def _list_cache() -> Any:
    from cndb.core.cache import list_cache

    return list_cache


def _team_brief(db: Session, workspace: Workspace) -> dict[str, Any] | None:
    """工作区所属团队简要信息（无团队返回 None）."""
    if not workspace.team_id:
        return None
    team = db.get(Team, workspace.team_id)
    if team is None:  # pragma: no cover - FK 保证存在（删团队会置空 team_id）
        return None
    return {"id": team.id, "name": team.name, "slug": team.slug}


def _workspace_payload(db: Session, workspace: Workspace) -> dict[str, Any]:
    """ORM → 响应载荷：列字段 + 团队简要信息（``team`` 不映射 ORM 关系，D3）."""
    data = {c.name: getattr(workspace, c.name) for c in workspace.__table__.columns}
    data["team"] = _team_brief(db, workspace)
    return data


def invalidate_workspace_list_cache(workspace_id: int | None = None) -> int:
    """失效所有用户的工作区列表缓存（成员/工作区变更后调用）.

    ``workspace_id`` 非空时同时失效该工作区的详情统计缓存（ADR 0046 D5）。
    """
    from cndb.core.cache import cache_key, list_cache, search_cache

    cleared = list_cache.clear(cache_key("ws-list"))
    # 成员变化会改变「能搜到哪些工作区」：跨工作区 / 团队内检索一并失效（ADR 0153 P2）
    cleared += search_cache.clear(cache_key("global-search"))
    cleared += search_cache.clear(cache_key("team-search"))
    if workspace_id is not None:
        cleared += list_cache.clear(cache_key("workspace-stats", workspace_id))
    return cleared


router = APIRouter(prefix="/workspaces", tags=["workspaces"])
# 成员管理 / 所有权转让拆到 routers/member_routes.py（同一前缀下挂载）
router.include_router(member_router)

# ── 工作区 CRUD ──────────────────────────────────────


@router.get("", response_model=list[WorkspaceWithPinnedResponse])
def list_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    team_id: int | None = None,
) -> list[WorkspaceWithPinnedResponse]:
    """列出当前用户所属的工作区，钉住的置顶，附带 table_count / member_count.

    ``team_id`` 可选：只返回该团队下的工作区（ADR 0153 C1 的平铺列表入口）。

    进程内短 TTL 缓存（10s，按用户 + 团队过滤隔离）：该接口每次都要做数次聚合统计，
    是首页最热的读路径；写路径（新建/改名/成员变更/团队变更）会主动失效，
    短 TTL 只是兜底 —— 单机部署下进程内缓存无需 Redis 即可生效。
    """
    from cndb.core.cache import cache_key

    cache = _list_cache()
    ck = cache_key("ws-list", current_user.id, team_id or 0, id(db.bind))
    cached = cache.get(ck)
    if cached is not None:
        return cached
    data = _list_workspaces_uncached(db, current_user, team_id=team_id)
    cache.set(ck, data, WORKSPACE_LIST_TTL_SECONDS)
    return data


def _list_workspaces_uncached(
    db: Session,
    current_user: User,
    *,
    team_id: int | None = None,
) -> list[WorkspaceWithPinnedResponse]:
    from sqlalchemy import case, func, select

    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.services.stats_cache import compute_content_counts

    stmt = (
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(case((WorkspaceMember.pinned.is_(True), 0), else_=1), Workspace.id)
    )
    if team_id:
        stmt = stmt.where(Workspace.team_id == team_id)
    rows = db.execute(stmt).all()

    # 批量收集 workspace_id 用于统计
    ws_ids = [ws.id for ws, _ in rows]
    # 表数统计（排除软删）
    table_counts: dict[int, int] = {
        row[0]: row[1]
        for row in (
            db.query(DataTable.workspace_id, func.count(DataTable.id))
            .filter(DataTable.workspace_id.in_(ws_ids), DataTable.trashed_at.is_(None))
            .group_by(DataTable.workspace_id)
            .all()
        )
    }
    # 成员数统计（inner join 用户表：历史脏数据中用户已删除的孤儿成员行不计入，
    # 保证计数与成员列表一致）
    member_counts: dict[int, int] = {
        row[0]: row[1]
        for row in (
            db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
            .join(User, User.id == WorkspaceMember.user_id)
            .filter(WorkspaceMember.workspace_id.in_(ws_ids))
            .group_by(WorkspaceMember.workspace_id)
            .all()
        )
    }
    # 文档 / 设计计数（需求 0093）：分组 COUNT，文件夹 / 回收站 / 软删不计入
    content_counts = compute_content_counts(db, ws_ids)
    # 团队简要信息（ADR 0153）：列表按团队分组展示，一次批量取
    team_ids = {ws.team_id for ws, _ in rows if ws.team_id}
    team_briefs: dict[int, dict[str, Any]] = {}
    if team_ids:
        for team in db.query(Team).filter(Team.id.in_(team_ids)).all():
            team_briefs[team.id] = {"id": team.id, "name": team.name, "slug": team.slug}
    result: list[WorkspaceWithPinnedResponse] = []
    for ws, member in rows:
        d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
        d["team"] = team_briefs.get(ws.team_id) if ws.team_id else None
        d["pinned"] = bool(member.pinned)
        # 统计字段塞进 response 扩展（WorkspaceWithPinnedResponse 继承自 WorkspaceResponse，
        # 前端列表类型声明时用 Workspace & { table_count, member_count } 接收）
        d["table_count"] = table_counts.get(ws.id, 0)
        d["member_count"] = member_counts.get(ws.id, 0)
        counts = content_counts.get(ws.id) or {}
        d["document_count"] = counts.get("document_count", 0)
        d["design_count"] = counts.get("design_count", 0)
        d["current_user_role"] = member.role.value if member.role else None
        result.append(WorkspaceWithPinnedResponse.model_validate(d))
    return result


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceResponse:
    """创建工作区并把创建者登记为 OWNER（可选挂到团队，ADR 0153 D3）."""
    team: Team | None = None
    policy: dict[str, Any] = {}
    if payload.team_id is not None:
        team = _require_team_for_workspace(
            db, payload.team_id, current_user, requirement="仅团队成员可在团队下创建工作区"
        )
        policy = team_policy_for(team)
        if policy.get("allowed_modules") is not None:
            ensure_modules_allowed(policy, payload.modules)
    quota = policy.get("default_storage_quota_bytes")
    ws = Workspace(
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        tags=payload.tags,
        allow_edit=payload.allow_edit,
        modules=payload.modules,
        team_id=payload.team_id,
        storage_quota_bytes=quota if isinstance(quota, int) else DEFAULT_STORAGE_QUOTA_BYTES,
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id
    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    db.refresh(ws)
    invalidate_workspace_list_cache(ws.id)
    return WorkspaceResponse.model_validate(_workspace_payload(db, ws))


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceDetailResponse:
    """获取工作区详情（需是成员），附带拥有者信息和统计."""
    from cndb.plugins.workspaces.services.stats_cache import compute_content_stats, get_workspace_stats
    from cndb.plugins.workspaces.services.storage_snapshot import snapshot_used_bytes

    ws = _get_workspace_or_404(workspace_id, db)
    caps = _require_member(ws, current_user, db)

    # 统计（table/member/view/total_rows）：UNION ALL + 30s 缓存，见 ADR 0046 D5
    stats = get_workspace_stats(db, workspace_id)
    # 文档 / 设计计数实时计算（写路径无统一缓存事件，避免设置页显示旧值）
    content_stats = compute_content_stats(db, workspace_id)

    # 拥有者信息
    owner_member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .first()
    )
    owner_info: dict[str, Any] | None = None
    if owner_member and owner_member.user:
        owner_info = {
            "id": owner_member.user.id,
            "username": owner_member.user.username,
            "nickname": owner_member.user.nickname,
        }

    current_role = caps.data_role
    d = _workspace_payload(db, ws)
    d.update(
        {
            "owner": owner_info,
            "table_count": stats["table_count"],
            "member_count": stats["member_count"],
            "view_count": stats["view_count"],
            "total_rows": stats["total_rows"],
            "document_count": content_stats["document_count"],
            "design_count": content_stats["design_count"],
            # 读用量快照（ADR 0024），缺失时懒计算一次并落库
            "storage_bytes": snapshot_used_bytes(db, workspace_id, lazy=True) or 0,
            "current_user_role": current_role.value if current_role else None,
        }
    )
    return WorkspaceDetailResponse.model_validate(d)


@router.get(
    "/{workspace_id}/capabilities",
    response_model=WorkspaceCapabilitiesResponse,
    summary="工作区能力位（前端门控唯一数据源，ADR 0153）",
)
def get_workspace_capabilities(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceCapabilitiesResponse:
    """返回当前用户在该工作区的能力位与来源归因（非成员统一 404）.

    前端 ``useCapabilities`` 只消费本端点，替换散落的 ``current_user_role`` 判断；
    P1 接入团队层时载荷只增 ``team_role`` / 策略默认来源，不改变形状。
    """
    ws = _get_workspace_or_404(workspace_id, db)
    caps = resolve_capabilities(current_user, ws, db)
    if caps.data_role is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return WorkspaceCapabilitiesResponse.model_validate(caps.to_payload())


@router.post("/{workspace_id}/join", response_model=PinToggleResponse, status_code=status.HTTP_200_OK)
def join_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PinToggleResponse:
    """团队成员自助加入团队工作区（ADR 0153 P2，需团队策略 `allow_member_invite`）.

    角色 = 团队策略 `default_workspace_role`（viewer / editor），`none` 时按 viewer 加入；
    已是成员时幂等返回当前状态，不改变既有角色。
    """
    from cndb.core.events import record_event
    from cndb.plugins.workspaces.services.teams import team_policy_for

    ws = _get_workspace_or_404(workspace_id, db)
    if ws.team_id is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    team = db.get(Team, ws.team_id)
    if team is None:  # pragma: no cover - FK 保证存在
        raise HTTPException(status_code=404, detail="工作区不存在")
    membership = (
        db.query(TeamMember).filter(TeamMember.team_id == team.id, TeamMember.user_id == current_user.id).first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="工作区不存在")

    existing = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == current_user.id)
        .first()
    )
    if existing is not None:
        return PinToggleResponse(pinned=bool(existing.pinned))

    policy = team_policy_for(team)
    if not bool(policy.get("allow_member_invite", False)):
        raise HTTPException(status_code=403, detail="该团队未开放自助加入，请联系团队管理员")
    from cndb.plugins.workspaces.permissions import policy_default_role

    role = policy_default_role(policy) or WorkspaceRole.VIEWER
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=role))
    record_event(
        db,
        "workspace.member_join",
        summary=f"{current_user.nickname or current_user.username} 自助加入工作区「{ws.name}」",
        target_type="workspace",
        target_id=ws.id,
        workspace_id=ws.id,
        actor_id=current_user.id,
        actor_name=current_user.nickname or current_user.username,
        detail={"role": role.value, "team_id": team.id},
        commit=False,
    )
    db.commit()
    invalidate_workspace_list_cache(ws.id)
    return PinToggleResponse(pinned=False)


@router.get(
    "/{workspace_id}/stats/contributions",
    response_model=WorkspaceContributionsResponse,
    summary="工作区贡献统计（按编辑者）",
)
def get_workspace_contributions(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceContributionsResponse:
    """按工作区编辑者聚合贡献（需求 0126，成员可读，全部时间）."""
    from cndb.plugins.workspaces.services.contributions import compute_workspace_contributions

    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)
    return WorkspaceContributionsResponse.model_validate(compute_workspace_contributions(db, workspace_id))


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceResponse:
    """更新工作区（仅 OWNER）."""
    ws = _get_workspace_or_404(workspace_id, db)
    # 管理面：工作区所有者或团队管理员（ADR 0153 D4）
    _require_owner(ws, current_user, db)
    update_data = payload.model_dump(exclude_unset=True)
    if "team_id" in update_data:
        target_team_id = update_data["team_id"]
        if target_team_id is not None:
            target_team = _require_team_for_workspace(
                db, target_team_id, current_user, requirement="仅目标团队成员可把工作区迁入该团队"
            )
            policy = team_policy_for(target_team)
            if policy.get("allowed_modules") is not None:
                ensure_modules_allowed(policy, update_data.get("modules") or list(ws.modules or []))
        # 解绑（target=None）不需额外团队校验：管理面已在上面通过（工作区所有者 / 团队管理员）
    for key, value in update_data.items():
        setattr(ws, key, value)
    db.commit()
    invalidate_workspace_list_cache(workspace_id)
    db.refresh(ws)
    return WorkspaceResponse.model_validate(_workspace_payload(db, ws))


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除工作区（仅 OWNER 可执行）."""
    ws = _get_workspace_or_404(workspace_id, db)
    # ADR 0047 / ADR 0153 D9：删除属不可逆操作，仅工作区所有者本人（团队管理员不行）
    _require_workspace_owner(ws, current_user, db, requirement="仅所有者可删除工作区")
    db.delete(ws)
    db.commit()
    invalidate_workspace_list_cache(workspace_id)


# ── pin 切换 ──────────────────────────────────────────


@router.post("/pin", response_model=PinToggleResponse)
def toggle_pin(
    payload: PinRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PinToggleResponse:
    """切换当前用户对工作区的钉住状态."""
    ws = _get_workspace_or_404(payload.workspace_id, db)
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == current_user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置
    member.pinned = not member.pinned
    db.commit()
    invalidate_workspace_list_cache()
    db.refresh(member)
    return PinToggleResponse(pinned=member.pinned)


def _row_scope_where(db: Any, tbl: Any, sa_table: Any, user: Any = None) -> Any | None:
    """编译该表的**读范围**条件（无配置或调用者豁免时返回 None）.

    ADR 0004：导出取数复用 ``row_access.row_read_scope_where``（默认档 ∪ 命中的行级规则），
    与记录读取 / 审计同一入口，导出不得越过读范围。
    """
    from cndb.plugins.tables.services.core.row_access import row_read_scope_where

    return row_read_scope_where(db, tbl, sa_table, user)


@router.get("/{workspace_id}/export")
def export_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """导出整个工作区为 JSON：工作区元信息 + 所有表结构 + 数据行 + 视图配置 + 表权限 + 文档（含标签）.

    v8 口径由 v9 全量构建器降采样生成（ADR 0075：新旧出口同一份数据来源）。
    """
    from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v8

    ws = _get_workspace_or_404(workspace_id, db)
    # 全量导出是备份/恢复的一侧，与 import_workspace 对称要求 EDITOR+：
    # 此前仅校验成员身份，任何 viewer 都能把所有表（含受限表）连数据行一起导出。
    require_capability(
        WorkspaceCapability.EXPORT,
        db,
        ws,
        current_user,
        requirement="编辑者及以上权限才能导出工作区",
    )

    return build_workspace_backup_v8(db, workspace_id, current_user)


@router.post("/import", response_model=WorkspaceCreateFromBackupResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_from_backup(
    payload: WorkspaceCreateFromBackup,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceCreateFromBackupResponse:
    """从备份 JSON 创建全新工作区：先创建工作区（owner 为当前用户），再把备份中的表结构、数据和视图导入."""
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的备份文件格式")

    # 从备份里读取 workspace meta 作为创建工作区的默认值
    ws_meta = data.get("workspace") or {}
    backup_name = payload.name or (ws_meta.get("name") or "").strip() or "未命名工作区"

    try:
        visibility_str = ws_meta.get("visibility", "member")
        visibility = WorkspaceVisibility(visibility_str)
    except (ValueError, TypeError):
        visibility = WorkspaceVisibility.MEMBER

    # v12 写 modules；≤v11 旧备份按 workspace_type 映射，未知值回退全模块并记 errors（ADR 0080 D7）
    modules, module_warning = workspace_modules_from_meta(ws_meta)

    ws = Workspace(
        name=backup_name,
        description=ws_meta.get("description", "") or "",
        visibility=visibility,
        tags=ws_meta.get("tags", []) or [],
        allow_edit=bool(ws_meta.get("allow_edit", True)),
        modules=modules,
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id

    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    db.refresh(ws)

    # 导入备份中的表/数据/视图
    try:
        import_result = import_backup_into_workspace(ws.id, data, current_user, db)
    except HTTPException:
        # 导入失败：清理刚创建的工作区，避免脏数据残留
        db.delete(ws)
        db.commit()
        raise

    if module_warning:
        import_result.errors.append(module_warning)

    return WorkspaceCreateFromBackupResponse(
        workspace=WorkspaceResponse.model_validate(_workspace_payload(db, ws)),
        imported_tables=import_result.imported_tables,
        imported_rows=import_result.imported_rows,
        imported_views=import_result.imported_views,
        imported_documents=import_result.imported_documents,
        imported_sync_jobs=import_result.imported_sync_jobs,
        imported_charts=import_result.imported_charts,
        errors=import_result.errors,
    )


@router.post("/{workspace_id}/import", response_model=WorkspaceImportResponse)
def import_workspace(
    workspace_id: int,
    payload: WorkspaceImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceImportResponse:
    """从 JSON 数据导入表结构、视图和数据行到指定工作区（EDITOR+）."""
    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(
        WorkspaceCapability.EXPORT,
        db,
        ws,
        current_user,
        requirement="编辑者及以上权限才能导入工作区",
    )
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的导入数据格式")

    return import_backup_into_workspace(workspace_id, data, current_user, db)


# ── v9 归档备份 / 覆盖恢复（ADR 0075） ──────────────────────────────


@router.get("/{workspace_id}/export/archive")
def export_workspace_archive(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_secrets: bool = True,
) -> FileResponse:
    """导出工作区全量备份归档（tar.gz：manifest + v16 backup.json + 表行分块 + 附件/外存文件）."""
    from cndb.plugins.workspaces.services.workspace_backup import (
        build_workspace_backup_v16,
        pack_workspace_archive,
        workspace_backup_filename,
    )

    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(
        WorkspaceCapability.EXPORT,
        db,
        ws,
        current_user,
        requirement="编辑者及以上权限才能导出工作区",
    )

    # 团队只作 manifest 提示性元数据（ADR 0153 D7）：不随工作区备份往返，导入不自动挂
    team_meta: dict[str, Any] | None = None
    if ws.team_id:
        team_row = db.get(Team, ws.team_id)
        if team_row is not None:
            team_meta = {"name": team_row.name, "slug": team_row.slug}

    # 表行按表写成 NDJSON 临时分块（ADR 0075 D8）：大工作区导出不再把全部行拼成一份巨型 JSON
    with tempfile.TemporaryDirectory(prefix="cndb-ws-export-rows-") as rows_dir:
        backup, files = build_workspace_backup_v16(
            db, workspace_id, current_user, include_secrets=include_secrets, rows_dir=Path(rows_dir)
        )
        fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-export-", suffix=".tar.gz")
        tmp_path = Path(tmp_name)
        import os

        os.close(fd)
        try:
            pack_workspace_archive(backup, files, tmp_path, team=team_meta)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    return FileResponse(
        tmp_path,
        media_type="application/gzip",
        filename=workspace_backup_filename(),
        background=BackgroundTask(lambda: tmp_path.unlink(missing_ok=True)),
    )


@router.post("/{workspace_id}/restore", response_model=WorkspaceImportResponse)
def restore_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> WorkspaceImportResponse:
    """从 v9 归档覆盖恢复当前工作区（**危险操作**：清空现有业务数据后全量重建，仅 OWNER）."""
    from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive
    from cndb.plugins.workspaces.services.workspace_restore import restore_workspace_from_backup

    ws = _get_workspace_or_404(workspace_id, db)
    # 覆盖恢复会清空业务数据：仅工作区所有者本人可执行（ADR 0153 D9）
    _require_workspace_owner(ws, current_user, db)

    fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-restore-", suffix=".tar.gz")
    tmp_path = Path(tmp_name)
    import os

    # 归档解析失败时上传副本必须清理，否则无效上传会在 /tmp 持续堆积（磁盘耗尽）
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(file.file, out)
        archive = parse_workspace_archive(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    try:
        result = restore_workspace_from_backup(workspace_id, archive.backup, archive.files_dir, current_user, db)
    finally:
        archive.cleanup()
        tmp_path.unlink(missing_ok=True)
    invalidate_workspace_list_cache(workspace_id)
    return result


@router.post("/import/archive/inspect", response_model=WorkspaceArchiveInspectResponse)
def inspect_workspace_archive(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> WorkspaceArchiveInspectResponse:
    """预检归档：返回归档内工作区名 / 版本 / 统计，以及同名且当前用户为 owner 的既有工作区.

    供导入对话框选择「导入为新工作区（推荐）」或「覆盖恢复到已有工作区」；
    不写库，解析失败按无效归档返回 400。
    """
    from sqlalchemy import select

    from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

    fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-inspect-", suffix=".tar.gz")
    tmp_path = Path(tmp_name)
    import os

    # 归档解析失败时上传副本必须清理，否则无效上传会在 /tmp 持续堆积（磁盘耗尽）
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(file.file, out)
        archive = parse_workspace_archive(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    try:
        data = archive.backup
        ws_meta = data.get("workspace") or {}
        backup_name = (ws_meta.get("name") or "").strip() or "未命名工作区"
        existing = db.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.user_id == current_user.id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
                Workspace.name == (ws_meta.get("name") or "").strip(),
            )
            .order_by(Workspace.id)
            .limit(1)
        ).scalar_one_or_none()
        manifest = archive.manifest
        created_at = manifest.get("created_at")
        return WorkspaceArchiveInspectResponse(
            workspace_name=backup_name,
            backup_version=str(data.get("version", "")),
            created_at=created_at,
            include_secrets=bool(manifest.get("include_secrets", True)),
            stats=manifest.get("stats") or {},
            existing_workspace=(WorkspaceArchiveTarget(id=existing.id, name=existing.name) if existing else None),
        )
    finally:
        archive.cleanup()
        tmp_path.unlink(missing_ok=True)


@router.post("/import/archive", response_model=WorkspaceCreateFromBackupResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_from_archive(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
) -> WorkspaceCreateFromBackupResponse:
    """从 v9 归档创建全新工作区（owner 为当前用户），与 JSON 导入互不干扰.

    ``name`` 非空时用作新工作区名称（前端默认填「归档名 + 导入时间后缀」便于区分，
    并允许用户修改）；为空时回落到归档内的 workspace.name。
    """
    from cndb.plugins.workspaces.services.workspace_import import create_workspace_from_archive_file

    fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-import-", suffix=".tar.gz")
    tmp_path = Path(tmp_name)
    import os

    # 归档解析失败时上传副本必须清理，否则无效上传会在 /tmp 持续堆积（磁盘耗尽）
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    try:
        result = create_workspace_from_archive_file(tmp_path, current_user, db, name=name)
    finally:
        tmp_path.unlink(missing_ok=True)

    invalidate_workspace_list_cache(result.workspace.id)
    return WorkspaceCreateFromBackupResponse(
        workspace=result.workspace,
        imported_tables=result.imported_tables,
        imported_rows=result.imported_rows,
        imported_views=result.imported_views,
        imported_documents=result.imported_documents,
        imported_sync_jobs=result.imported_sync_jobs,
        imported_charts=result.imported_charts,
        imported_pipelines=result.imported_pipelines,
        errors=result.errors,
    )


__all__ = ["_coerce_row_value_types", "router"]

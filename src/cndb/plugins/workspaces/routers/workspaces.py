"""workspaces 插件路由：CRUD + 成员管理 + pin + candidates."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceType,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.permissions import get_member_role, has_role, raise_permission_denied
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404, _require_member, _require_owner
from cndb.plugins.workspaces.routers.member_routes import router as member_router
from cndb.plugins.workspaces.schemas import (
    PinRequest,
    PinToggleResponse,
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
    _import_backup_into_workspace,
)

# 工作区列表缓存（进程内，短 TTL；写路径主动失效）
WORKSPACE_LIST_TTL_SECONDS = 10.0


def _list_cache() -> Any:
    from cndb.core.cache import list_cache

    return list_cache


def invalidate_workspace_list_cache(workspace_id: int | None = None) -> int:
    """失效所有用户的工作区列表缓存（成员/工作区变更后调用）.

    ``workspace_id`` 非空时同时失效该工作区的详情统计缓存（ADR 0046 D5）。
    """
    from cndb.core.cache import cache_key, list_cache

    cleared = list_cache.clear(cache_key("ws-list"))
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
) -> list[WorkspaceWithPinnedResponse]:
    """列出当前用户所属的工作区，钉住的置顶，附带 table_count / member_count.

    进程内短 TTL 缓存（10s，按用户隔离）：该接口每次都要做 3 次聚合统计，
    是首页最热的读路径；写路径（新建/改名/成员变更）会主动失效，
    短 TTL 只是兜底 —— 单机部署下进程内缓存无需 Redis 即可生效。
    """
    from cndb.core.cache import cache_key

    cache = _list_cache()
    ck = cache_key("ws-list", current_user.id, id(db.bind))
    cached = cache.get(ck)
    if cached is not None:
        return cached
    data = _list_workspaces_uncached(db, current_user)
    cache.set(ck, data, WORKSPACE_LIST_TTL_SECONDS)
    return data


def _list_workspaces_uncached(
    db: Session,
    current_user: User,
) -> list[WorkspaceWithPinnedResponse]:
    from sqlalchemy import case, func, select

    from cndb.plugins.tables.models import DataTable

    stmt = (
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(case((WorkspaceMember.pinned.is_(True), 0), else_=1), Workspace.id)
    )
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
    result: list[WorkspaceWithPinnedResponse] = []
    for ws, member in rows:
        d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
        d["pinned"] = bool(member.pinned)
        # 统计字段塞进 response 扩展（WorkspaceWithPinnedResponse 继承自 WorkspaceResponse，
        # 前端列表类型声明时用 Workspace & { table_count, member_count } 接收）
        d["table_count"] = table_counts.get(ws.id, 0)
        d["member_count"] = member_counts.get(ws.id, 0)
        d["current_user_role"] = member.role.value if member.role else None
        result.append(WorkspaceWithPinnedResponse.model_validate(d))
    return result


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """创建工作区并把创建者登记为 OWNER."""
    ws = Workspace(
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        tags=payload.tags,
        allow_edit=payload.allow_edit,
        workspace_type=payload.workspace_type,
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id
    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    invalidate_workspace_list_cache(ws.id)
    db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceDetailResponse:
    """获取工作区详情（需是成员），附带拥有者信息和统计."""
    from cndb.plugins.workspaces.services.stats_cache import get_workspace_stats
    from cndb.plugins.workspaces.services.storage_snapshot import snapshot_used_bytes

    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)

    # 统计（table/member/view/total_rows）：UNION ALL + 30s 缓存，见 ADR 0046 D5
    stats = get_workspace_stats(db, workspace_id)

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

    current_role = get_member_role(current_user, ws, db)
    d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
    d.update(
        {
            "owner": owner_info,
            "table_count": stats["table_count"],
            "member_count": stats["member_count"],
            "view_count": stats["view_count"],
            "total_rows": stats["total_rows"],
            # 读用量快照（ADR 0024），缺失时懒计算一次并落库
            "storage_bytes": snapshot_used_bytes(db, workspace_id, lazy=True) or 0,
            "current_user_role": current_role.value if current_role else None,
        }
    )
    return WorkspaceDetailResponse.model_validate(d)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """更新工作区（仅 OWNER）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_owner(ws, current_user, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ws, key, value)
    db.commit()
    invalidate_workspace_list_cache(workspace_id)
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除工作区（仅 OWNER 可执行）."""
    ws = _get_workspace_or_404(workspace_id, db)
    role = get_member_role(current_user, ws, db)
    if role != WorkspaceRole.OWNER:
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口）
        raise_permission_denied(db, ws, current_user, requirement="仅所有者可删除工作区")
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
    if not has_role(current_user, ws, WorkspaceRole.EDITOR, db):
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口）
        raise_permission_denied(db, ws, current_user, requirement="编辑者及以上权限才能导出工作区")

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

    try:
        workspace_type = WorkspaceType(ws_meta.get("workspace_type", WorkspaceType.DATA_DOC.value))
    except (ValueError, TypeError):
        workspace_type = WorkspaceType.DATA_DOC

    ws = Workspace(
        name=backup_name,
        description=ws_meta.get("description", "") or "",
        visibility=visibility,
        tags=ws_meta.get("tags", []) or [],
        allow_edit=bool(ws_meta.get("allow_edit", True)),
        workspace_type=workspace_type,
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
        import_result = _import_backup_into_workspace(ws.id, data, current_user, db)
    except HTTPException:
        # 导入失败：清理刚创建的工作区，避免脏数据残留
        db.delete(ws)
        db.commit()
        raise

    return WorkspaceCreateFromBackupResponse(
        workspace=ws,
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
    if not has_role(current_user, ws, WorkspaceRole.EDITOR, db):
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口）
        raise_permission_denied(db, ws, current_user, requirement="编辑者及以上权限才能导入工作区")
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的导入数据格式")

    return _import_backup_into_workspace(workspace_id, data, current_user, db)


# ── v9 归档备份 / 覆盖恢复（ADR 0075） ──────────────────────────────


@router.get("/{workspace_id}/export/archive")
def export_workspace_archive(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_secrets: bool = True,
) -> FileResponse:
    """导出工作区全量备份归档（tar.gz：manifest + v9 backup.json + 附件/外存文件）."""
    from cndb.plugins.workspaces.services.workspace_backup import (
        build_workspace_backup_v9,
        pack_workspace_archive,
        workspace_backup_filename,
    )

    ws = _get_workspace_or_404(workspace_id, db)
    if not has_role(current_user, ws, WorkspaceRole.EDITOR, db):
        raise_permission_denied(db, ws, current_user, requirement="编辑者及以上权限才能导出工作区")

    backup, files = build_workspace_backup_v9(db, workspace_id, current_user, include_secrets=include_secrets)
    fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-export-", suffix=".tar.gz")
    tmp_path = Path(tmp_name)
    import os

    os.close(fd)
    try:
        pack_workspace_archive(backup, files, tmp_path)
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
    _require_owner(ws, current_user, db)

    fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-restore-", suffix=".tar.gz")
    tmp_path = Path(tmp_name)
    import os

    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(file.file, out)

    archive = parse_workspace_archive(tmp_path)
    try:
        result = restore_workspace_from_backup(workspace_id, archive.backup, archive.files_dir, current_user, db)
    finally:
        archive.cleanup()
        tmp_path.unlink(missing_ok=True)
    invalidate_workspace_list_cache(workspace_id)
    return result


@router.post("/import/archive", response_model=WorkspaceCreateFromBackupResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_from_archive(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> WorkspaceCreateFromBackupResponse:
    """从 v9 归档创建全新工作区（owner 为当前用户），与 JSON 导入互不干扰."""
    from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

    fd, tmp_name = tempfile.mkstemp(prefix="cndb-ws-import-", suffix=".tar.gz")
    tmp_path = Path(tmp_name)
    import os

    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(file.file, out)

    archive = parse_workspace_archive(tmp_path)
    try:
        data = archive.backup
        if not isinstance(data, dict) or "tables" not in data:
            raise HTTPException(status_code=400, detail="无效的备份归档格式")

        ws_meta = data.get("workspace") or {}
        backup_name = (ws_meta.get("name") or "").strip() or "未命名工作区"
        try:
            visibility = WorkspaceVisibility(ws_meta.get("visibility", "member"))
        except (ValueError, TypeError):
            visibility = WorkspaceVisibility.MEMBER
        try:
            workspace_type = WorkspaceType(ws_meta.get("workspace_type", WorkspaceType.DATA_DOC.value))
        except (ValueError, TypeError):
            workspace_type = WorkspaceType.DATA_DOC

        ws = Workspace(
            name=backup_name,
            description=ws_meta.get("description", "") or "",
            visibility=visibility,
            tags=ws_meta.get("tags", []) or [],
            allow_edit=bool(ws_meta.get("allow_edit", True)),
            workspace_type=workspace_type,
            created_by_id=current_user.id,
        )
        db.add(ws)
        db.flush()
        member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
        db.add(member)
        db.commit()
        db.refresh(ws)

        try:
            import_result = _import_backup_into_workspace(ws.id, data, current_user, db, files_dir=archive.files_dir)
        except HTTPException:
            db.delete(ws)
            db.commit()
            raise
    finally:
        archive.cleanup()
        tmp_path.unlink(missing_ok=True)

    invalidate_workspace_list_cache(ws.id)
    return WorkspaceCreateFromBackupResponse(
        workspace=ws,
        imported_tables=import_result.imported_tables,
        imported_rows=import_result.imported_rows,
        imported_views=import_result.imported_views,
        imported_documents=import_result.imported_documents,
        imported_sync_jobs=import_result.imported_sync_jobs,
        imported_charts=import_result.imported_charts,
        errors=import_result.errors,
    )


__all__ = ["_coerce_row_value_types", "router"]

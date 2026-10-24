"""系统管理级 API — 备份 / 恢复 / 健康信息.

与业务插件（workspaces/tables）解耦，直接挂载到 FastAPI app.
所有端点需要 superuser 权限。
"""

from __future__ import annotations

import datetime as dt
import io
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cndb.cli.backup import BackupError, create_backup, format_backup_filename
from cndb.cli.restore import (
    RestoreError,
    _schema_revision_known,
    classify_table_groups,
    inspect_backup,
    restore_backup,
)
from cndb.core.config import DATA_DIR
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User, UserRole

if TYPE_CHECKING:
    from fastapi import FastAPI


def _require_superuser(current_user: User | None) -> None:
    """依赖：要求认证用户是 superuser 或 system_admin."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not (current_user.is_superuser or current_user.role == UserRole.SYSTEM_ADMIN.value):
        raise HTTPException(status_code=403, detail="需要系统管理员权限")


class SystemAbout(BaseModel):
    """普通用户可查看的系统基本信息（不含服务器路径等管理敏感字段）."""

    app_name: str
    app_version: str
    auth_enabled: bool
    timezone: str
    server_time: str


class WorkspaceStorageQuotaUpdate(BaseModel):
    """调整工作区存储配额请求（字节）."""

    quota_bytes: int


class WorkspaceStorageRefreshRequest(BaseModel):
    """触发用量快照重算（缺省 = 全部工作区）."""

    workspace_ids: list[int] | None = None


def register_system_routes(app: FastAPI) -> None:
    """将系统管理路由挂载到 FastAPI app.

    管理路由统一前缀 ``/api/v1/admin``（需 superuser）；
    普通信息路由前缀 ``/api/v1/system``（登录即可，普通用户可访问）。
    """
    from fastapi import APIRouter, Body

    from cndb.api.deps import get_current_user

    router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

    @router.get("/cache/stats")
    def cache_stats(current_user: User | None = Depends(get_current_user)) -> dict[str, Any]:
        """缓存统计（命中率/条目数）——进程内缓存运维用，仅超级管理员."""
        _require_superuser(current_user)
        from cndb.core.cache import list_cache, meta_cache

        return {
            "list": list_cache.stats().as_dict(),
            "meta": meta_cache.stats().as_dict(),
        }

    @router.post("/cache/clear")
    def cache_clear(
        current_user: User | None = Depends(get_current_user),
        prefix: str | None = None,
    ) -> dict[str, Any]:
        """清除进程内缓存（可按前缀）——仅超级管理员，用于排障/压测 A-B."""
        _require_superuser(current_user)
        from cndb.core.cache import invalidate_all

        return {"cleared": invalidate_all(prefix), "prefix": prefix}

    @router.get("/info")
    def admin_info(current_user: User | None = Depends(get_current_user)) -> dict[str, Any]:
        """系统信息（版本/数据库/数据目录）— 登录即可."""
        from cndb.core.config import settings

        if current_user is None:
            raise HTTPException(status_code=401, detail="未登录")
        return {
            "app_name": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "database_url": settings.DATABASE_URL,
            "upload_dir": str(settings.UPLOAD_DIR),
            "data_dir": str(DATA_DIR),
            "auth_enabled": settings.AUTH_ENABLED,
            "timezone": "UTC",
        }

    @router.get("/workspaces/storage")
    def admin_workspace_storage(
        current_user: User | None = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """工作区空间分配总览 —— 只读用量快照，请求内不做统计（仅系统管理员）.

        用量由后台刷新线程按周期重算（ADR 0024）；本端点一次 JOIN 取齐快照与配额，
        响应时间不再随工作区数据量增长。`used_bytes` 为 null 表示该工作区尚未统计。
        """
        _require_superuser(current_user)
        from cndb.core.config import settings
        from cndb.core.storage_refresh import get_storage_refresher
        from cndb.plugins.workspaces.models import (
            DEFAULT_STORAGE_QUOTA_BYTES,
            Workspace,
            WorkspaceMember,
            WorkspaceRole,
        )
        from cndb.plugins.workspaces.services.storage import workspace_quota_bytes
        from cndb.plugins.workspaces.services.storage_snapshot import (
            read_snapshots,
            snapshot_age_seconds,
            snapshot_computed_at,
        )

        interval = settings.STORAGE_SNAPSHOT_INTERVAL_SECONDS
        # 「过期」阈值：两个同步周期（关掉定时轮次时按 1 小时兜底）
        stale_after = max(60, interval * 2) if interval > 0 else 3600

        workspaces = db.query(Workspace).order_by(Workspace.id).all()
        # 拥有者用户名：一次性查出，避免逐工作区查询
        owner_ids = {
            row[0]: row[1]
            for row in db.query(WorkspaceMember.workspace_id, WorkspaceMember.user_id)
            .filter(WorkspaceMember.role == WorkspaceRole.OWNER)
            .all()
        }
        usernames = {
            row[0]: row[1]
            for row in db.query(User.id, User.username).filter(User.id.in_(set(owner_ids.values()) or {-1})).all()
        }
        snapshots = read_snapshots(db, [ws.id for ws in workspaces])
        items: list[dict[str, Any]] = []
        for ws in workspaces:
            snapshot = snapshots.get(ws.id)
            age = snapshot_age_seconds(snapshot)
            items.append(
                {
                    "workspace_id": ws.id,
                    "name": ws.name,
                    "owner_username": usernames.get(owner_ids.get(ws.id)),
                    "used_bytes": None if snapshot is None else snapshot.used_bytes,
                    "quota_bytes": workspace_quota_bytes(ws),
                    "computed_at": snapshot_computed_at(snapshot),
                    "age_seconds": age,
                    "is_stale": age is None or age > stale_after,
                    "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
                }
            )
        refresher = get_storage_refresher()
        ages = [item["age_seconds"] for item in items if item["age_seconds"] is not None]
        return {
            "default_quota_bytes": DEFAULT_STORAGE_QUOTA_BYTES,
            "items": items,
            # 最新一份快照有多旧（全部未统计时为 null）→ 页面「数据更新于 X 前」
            "snapshot_age_seconds": min(ages) if ages else None,
            "refresh_interval_seconds": interval,
            "refreshing": bool(refresher is not None and refresher.is_refreshing()),
            "pending_workspace_count": sum(1 for item in items if item["used_bytes"] is None),
        }

    @router.post("/workspaces/storage/refresh", status_code=202)
    def admin_refresh_workspace_storage(
        payload: WorkspaceStorageRefreshRequest | None = Body(default=None),
        current_user: User | None = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """投递用量重算请求（异步，立即返回 202）——仅系统管理员.

        body 省略或 `workspace_ids` 为空 = 全部工作区。实际统计由后台刷新线程执行，
        接口本身不做任何扫描；前端据 `computed_at` 变化判断是否完成。
        """
        _require_superuser(current_user)
        from cndb.plugins.workspaces.models import Workspace
        from cndb.plugins.workspaces.services.storage_snapshot import request_refresh

        requested = payload.workspace_ids if payload is not None else None
        accepted: list[int] = []
        if requested:
            existing = {row[0] for row in db.query(Workspace.id).filter(Workspace.id.in_(requested)).all()}
            missing = sorted(set(requested) - existing)
            if missing:
                raise HTTPException(status_code=404, detail=f"工作区不存在: {missing}")
            accepted = sorted(existing)
            request_refresh(accepted)
        else:
            request_refresh(None)
        return {"status": "accepted", "workspace_ids": accepted, "all": not accepted}

    @router.patch("/workspaces/{workspace_id}/storage-quota")
    def admin_update_workspace_quota(
        workspace_id: int,
        payload: WorkspaceStorageQuotaUpdate,
        current_user: User | None = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """调整某个工作区的存储配额（仅系统管理员）.

        配额不影响用量口径，因此不触发重算：`used_bytes` 读快照（缺失时懒计算一次）。
        """
        _require_superuser(current_user)
        from cndb.plugins.workspaces.models import Workspace
        from cndb.plugins.workspaces.services.storage_snapshot import snapshot_used_bytes

        if payload.quota_bytes < 0:
            raise HTTPException(status_code=400, detail="配额不能为负数")
        ws = db.get(Workspace, workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="工作区不存在")
        ws.storage_quota_bytes = payload.quota_bytes
        db.commit()
        db.refresh(ws)
        return {
            "workspace_id": ws.id,
            "used_bytes": snapshot_used_bytes(db, ws.id, lazy=True),
            "quota_bytes": ws.storage_quota_bytes,
        }

    # 普通用户可见的系统基本信息（登录即可，不含服务器路径等敏感字段）
    system_router = APIRouter(prefix="/api/v1/system", tags=["system"])

    @system_router.get("/about", response_model=SystemAbout)
    def system_about(current_user: User | None = Depends(get_current_user)) -> SystemAbout:
        """系统基本信息（应用名/版本/鉴权开关/时区/服务器时间）— 登录即可."""
        from cndb.core.config import settings

        if current_user is None:
            raise HTTPException(status_code=401, detail="未登录")
        return SystemAbout(
            app_name=settings.APP_NAME,
            app_version=settings.APP_VERSION,
            auth_enabled=settings.AUTH_ENABLED,
            timezone="UTC",
            server_time=dt.datetime.now(dt.UTC).isoformat(),
        )

    app.include_router(system_router)

    @router.post("/backup")
    def admin_backup(
        current_user: User | None = Depends(get_current_user),
        format: str = Body(default="archive", embed=True),
        include_uploads: bool = Body(default=True, embed=True),
        mode: str = Body(default="auto", embed=True),
    ) -> StreamingResponse:
        """创建系统级备份并返回可下载的 .tar.gz.

        Args:
            format: ``archive``（返回 tar.gz 下载流） / ``directory``（暂不支持，web 场景无法选路径）
            include_uploads: 是否包含附件目录
            mode: 备份模式 auto/native/sqlalchemy
        """
        _require_superuser(current_user)

        if format != "archive":
            raise HTTPException(
                status_code=400,
                detail="Web 管理台仅支持 archive 格式（tar.gz）。目录模式请使用 CLI：cndb backup --dir -o <路径>",
            )

        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        tmp_dir = Path(tempfile.mkdtemp(prefix="cndb-api-backup-"))
        archive_path = tmp_dir / f"tmp-{ts}.tar.gz"

        try:
            create_backup(
                output=archive_path,
                mode=mode,
                include_uploads=include_uploads,
                fmt="archive",
            )
            # 读取后立即清理临时目录
            data = archive_path.read_bytes()
        except BackupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"备份文件读取失败: {exc}") from exc
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # 下载文件名统一带软件版本与数据库格式版本（与 CLI 默认名同一格式契约）
        filename = format_backup_filename()
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/restore/inspect")
    async def admin_restore_inspect(
        file: UploadFile,
        current_user: User | None = Depends(get_current_user),
    ) -> dict[str, Any]:
        """dry-run 检查上传的备份文件，返回 manifest 元信息."""
        _require_superuser(current_user)

        tmp = Path(tempfile.mkdtemp(prefix="cndb-api-restore-"))
        archive_path = tmp / "uploaded.tar.gz"
        try:
            content = await file.read()
            archive_path.write_bytes(content)
            info = inspect_backup(archive_path)
        except RestoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        manifest: dict[str, Any] = dict(info.manifest)
        # 附加 schema 领先判定：备份 revision 不在本地迁移链上时，
        # native 恢复将失败，前端据此提示改用 sqlalchemy 降级恢复
        db = manifest.get("database", {})
        schema_version = str(db.get("schema_version", "") or "")
        manifest["schema_known"] = _schema_revision_known(schema_version) if schema_version else True
        manifest["backup_ahead"] = bool(
            db.get("backup_mode", "") == "native" and schema_version and not manifest["schema_known"]
        )
        # 表清单按「系统表 / 用户表」分类，供前端分组展示（用户表为 table_/trash_/link_ 前缀）
        manifest["table_groups"] = classify_table_groups(list(db.get("tables", []) or []))
        return manifest

    @router.post("/restore")
    async def admin_restore(
        file: UploadFile,
        mode: str | None = Form(default=None),
        force: bool = Form(default=True),
        current_user: User | None = Depends(get_current_user),
    ) -> dict[str, Any]:
        """从上传的备份文件恢复系统数据（破坏性操作）.

        Args:
            file: 上传的 .tar.gz 备份归档.
            mode: 覆盖恢复模式 — ``native`` / ``sqlalchemy``。None 时按备份标记分支；
                备份 schema 新于当前程序时可显式指定 sqlalchemy 降级恢复.
            force: 强制覆盖（恢复即覆盖，恒为 True）.
        """
        _require_superuser(current_user)

        tmp = Path(tempfile.mkdtemp(prefix="cndb-api-restore-"))
        archive_path = tmp / "uploaded.tar.gz"
        try:
            content = await file.read()
            archive_path.write_bytes(content)
            inspect_backup(archive_path)  # 前置完整性检查
            loss = restore_backup(archive_path, force=force, mode=mode)
        except RestoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"恢复失败: {exc}") from exc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 降级恢复（sqlalchemy 交集导入）的裁剪报告：显式呈现跳过表/丢弃列
        report: dict[str, Any] | None = None
        if loss is not None and loss.has_loss:
            report = {
                "skipped_tables": loss.skipped_tables,
                "dropped_columns": loss.dropped_columns,
                "summary": loss.summary(),
            }

        return {
            "status": "ok",
            "message": "恢复完成。建议在空闲时重启服务以确保所有组件状态一致。",
            "loss_report": report,
        }

    app.include_router(router)

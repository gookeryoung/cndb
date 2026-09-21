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

from cndb.backup import BackupError, create_backup
from cndb.core.config import DATA_DIR
from cndb.plugins.accounts.models import User, UserRole
from cndb.restore import RestoreError, _schema_revision_known, inspect_backup, restore_backup

if TYPE_CHECKING:
    from fastapi import FastAPI


def _require_superuser(current_user: User | None) -> None:
    """依赖：要求认证用户是 superuser 或 system_admin."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not (current_user.is_superuser or current_user.role == UserRole.SYSTEM_ADMIN.value):
        raise HTTPException(status_code=403, detail="需要系统管理员权限")


def register_system_routes(app: FastAPI) -> None:
    """将系统管理路由挂载到 FastAPI app.

    所有路由统一前缀 ``/api/v1/admin``。
    """
    from fastapi import APIRouter, Body

    from cndb.api.deps import get_current_user

    router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

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
        archive_path = tmp_dir / f"backup-{ts}.tar.gz"

        try:
            create_backup(
                output=archive_path,
                mode=mode,
                include_uploads=include_uploads,
                fmt="archive",
            )
        except BackupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # 读取后立即清理临时目录
        data = archive_path.read_bytes()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        filename = f"cndb-backup-{ts}.tar.gz"
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

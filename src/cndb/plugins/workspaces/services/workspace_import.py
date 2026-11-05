"""工作区归档导入的唯一落库入口（ADR 0075 / 需求 0106）.

`POST /v1/workspaces/import/archive` 与帮助页「创建示例工作区」共用本模块：
都按「新建工作区 + 归档落库」语义执行，归档内的表 / 字段 / 行 / 文档 ID 由
`_import_backup_into_workspace` 统一重映射，不新增第二套导入链路。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.modules import workspace_modules_from_meta
from cndb.plugins.workspaces.services.backup_io import _import_backup_into_workspace


@dataclass
class ArchiveWorkspaceImportResult:
    """归档导入结果（由路由层转换为响应模型）."""

    workspace: Workspace
    imported_tables: int
    imported_rows: int
    imported_views: int
    imported_documents: int = 0
    imported_sync_jobs: int = 0
    imported_charts: int = 0
    imported_pipelines: int = 0
    errors: list[str] = field(default_factory=list)


def create_workspace_from_archive_file(
    path: Path,
    current_user: User,
    db: Session,
    name: str | None = None,
) -> ArchiveWorkspaceImportResult:
    """从 v9 归档创建全新工作区（owner 为当前用户）.

    归档解析失败按 400；导入过程中抛出 HTTPException 时回滚新建的工作区，
    不残留半成品（既有导入失败语义保持不变）。
    """
    from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

    archive = parse_workspace_archive(path)
    try:
        data = archive.backup
        if not isinstance(data, dict) or "tables" not in data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的备份归档格式")

        ws_meta = data.get("workspace") or {}
        backup_name = (name or "").strip()[:255] or (ws_meta.get("name") or "").strip() or "未命名工作区"
        try:
            visibility = WorkspaceVisibility(ws_meta.get("visibility", "member"))
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

    errors = list(import_result.errors)
    if module_warning:
        errors.append(module_warning)
    return ArchiveWorkspaceImportResult(
        workspace=ws,
        imported_tables=import_result.imported_tables,
        imported_rows=import_result.imported_rows,
        imported_views=import_result.imported_views,
        imported_documents=import_result.imported_documents,
        imported_sync_jobs=import_result.imported_sync_jobs,
        imported_charts=import_result.imported_charts,
        imported_pipelines=import_result.imported_pipelines,
        errors=errors,
    )


__all__ = ["ArchiveWorkspaceImportResult", "create_workspace_from_archive_file"]

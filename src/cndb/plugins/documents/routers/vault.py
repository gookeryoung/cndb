"""documents 插件：Obsidian 文档库（vault）导入 / 导出路由.

端点：
- ``POST /{workspace_id}/documents/import/analyze``  只读预览（multipart 上传 zip，不落库）
- ``POST /{workspace_id}/documents/import``          导入（multipart zip + 选项）
- ``GET  /{workspace_id}/documents/export/vault``    导出为 Obsidian 库（zip 字节流）

**注册顺序**：本路由在 ``plugin.register_routes`` 中先于主文档路由挂载，
否则 ``/import``、``/export/vault`` 会被 ``/{doc_id}`` 一族通配路径抢先匹配。
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.routers.documents import invalidate_document_tree_cache, invalidate_tree_on_write
from cndb.plugins.documents.services import obsidian
from cndb.plugins.workspaces.models import Workspace
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(
    prefix="/{workspace_id}/documents",
    tags=["documents-vault"],
    dependencies=[Depends(invalidate_tree_on_write)],
)


async def _read_archive(file: UploadFile) -> obsidian.VaultArchive:
    """读入上传的 zip 并封装为受限读取器（体积 / 路径 / 解压炸弹校验在其内部）."""
    filename = file.filename or ""
    if filename and not filename.lower().endswith(".zip"):
        raise BadRequestError("只支持 .zip 压缩包：请把 Obsidian 库文件夹压缩为 zip 后上传")
    try:
        data = await file.read()
    except OSError as exc:  # pragma: no cover - 读取失败
        raise BadRequestError(f"读取上传文件失败：{exc}") from exc
    if not data:
        raise BadRequestError("上传文件为空")
    return obsidian.VaultArchive(data, filename)


def _require_member(db: Session, workspace_id: int, user: User) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("工作区不存在")
    if get_member_role(user, workspace, db) is None:
        from cndb.core.errors import PermissionDeniedError

        raise PermissionDeniedError("非工作区成员")
    return workspace


@router.post("/import/analyze")
async def analyze_document_vault(
    workspace_id: int,
    file: Annotated[UploadFile, File(..., description="Obsidian 库 zip 包")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    parent_id: Annotated[int | None, Form(description="导入到哪个文件夹（空 = 根目录）")] = None,
) -> dict[str, Any]:
    """解析库并返回导入预览（不写任何数据）.

    返回笔记/文件夹/附件数量、冲突清单（同名文档）、标签、告警与被忽略条目，
    前端据此让用户确认冲突策略后再调用 ``POST /import``。
    """
    _require_member(db, workspace_id, current_user)
    archive = await _read_archive(file)
    return obsidian.analyze_vault(db, workspace_id, current_user, archive, parent_id=parent_id)


@router.post("/import")
async def import_document_vault(
    workspace_id: int,
    file: Annotated[UploadFile, File(..., description="Obsidian 库 zip 包")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    parent_id: Annotated[int | None, Form(description="导入到哪个文件夹（空 = 根目录）")] = None,
    conflict: Annotated[str, Form(description="冲突策略：skip / rename / overwrite")] = obsidian.CONFLICT_RENAME,
    import_attachments: Annotated[bool, Form(description="是否导入图片等附件")] = True,
    import_tags: Annotated[bool, Form(description="是否按 front-matter 建标签")] = True,
    status: Annotated[str, Form(description="新建文档的状态：draft / published / archived")] = "draft",
) -> dict[str, Any]:
    """把 Obsidian 库导入为文档树（文件夹 + 文档 + 标签 + 附件）."""
    _require_member(db, workspace_id, current_user)
    archive = await _read_archive(file)
    stats = obsidian.import_vault(
        db,
        workspace_id,
        current_user,
        archive,
        parent_id=parent_id,
        conflict=conflict,
        create_tags=import_tags,
        import_attachments=import_attachments,
        status=status,
    )
    # 文档树缓存按用户隔离，写后立即失效由路由依赖负责；这里补一次防并发读回填
    invalidate_document_tree_cache(workspace_id)
    return stats


@router.get("/export/vault")
def export_document_vault(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    """导出当前工作区文档树为 Obsidian 库（zip）.

    结构：``<库名>/<文件夹>/<标题>.md`` + ``attachments/`` + 最小 ``.obsidian/app.json``；
    只导出当前用户可见的文档（未发布草稿仍按可见性规则裁剪）。
    """
    workspace = _require_member(db, workspace_id, current_user)
    data, filename = obsidian.export_vault(
        db,
        workspace_id,
        current_user,
        workspace_name=workspace.name or "",
    )
    quoted = quote(filename)
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"vault.zip\"; filename*=UTF-8''{quoted}",
        },
    )


__all__ = ["router"]

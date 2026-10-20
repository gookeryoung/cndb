"""documents 插件：通用文件导入路由（单文件 / 文件夹，md / docx / html）.

端点：
- ``POST /{workspace_id}/documents/import/files/analyze``  只读预览（multipart 文件批次，不落库）
- ``POST /{workspace_id}/documents/import/files``          导入（multipart 文件批次 + 选项）

**注册顺序**：本路由在 ``plugin.register_routes`` 中先于主文档路由挂载，
否则 ``/import/files`` 会被 ``/{doc_id}`` 一族通配路径抢先匹配。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.routers.documents import invalidate_document_tree_cache, invalidate_tree_on_write
from cndb.plugins.documents.routers.vault import _require_member
from cndb.plugins.documents.services import importers
from cndb.plugins.documents.services.obsidian import CONFLICT_RENAME, DETAIL_LIMIT

router = APIRouter(
    prefix="/{workspace_id}/documents",
    tags=["documents-import"],
    dependencies=[Depends(invalidate_tree_on_write)],
)


async def _collect_items(
    files: list[UploadFile], paths: list[str] | None
) -> tuple[list[importers.UploadedItem], list[dict[str, str]]]:
    """把上传文件与相对路径组装为批次：路径非法 / 隐藏项记入 ``invalid`` 后跳过."""
    items: list[importers.UploadedItem] = []
    invalid: list[dict[str, str]] = []
    path_list = paths or []
    for index, upload in enumerate(files):
        raw = path_list[index] if index < len(path_list) else (upload.filename or "")
        normalized = importers.normalize_path(raw)
        if normalized is None:
            invalid.append({"path": raw or "(空路径)", "reason": "路径非法或被忽略（绝对路径 / .. / 隐藏项）"})
            continue
        try:
            data = await upload.read()
        except OSError as exc:  # pragma: no cover - 读取失败
            invalid.append({"path": normalized, "reason": f"读取失败：{exc}"})
            continue
        items.append(importers.UploadedItem(path=normalized, data=data))
    return items, invalid


def _merge_skipped(result: dict[str, Any], invalid: list[dict[str, str]], key: str) -> None:
    """把路径非法项并入结果既有跳过明细（保持明细上限）."""
    if not invalid:
        return
    result[key] = (invalid + list(result.get(key) or []))[:DETAIL_LIMIT]


@router.post("/import/files/analyze")
async def analyze_document_files(
    workspace_id: int,
    files: Annotated[list[UploadFile], File(description="待导入文件（支持文件夹模式的多个文件）")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    paths: Annotated[list[str] | None, Form(description="与 files 一一对应的批次内相对路径")] = None,
    parent_id: Annotated[int | None, Form(description="导入到哪个文件夹（空 = 根目录）")] = None,
) -> dict[str, Any]:
    """解析文件批次并返回导入预览（不写任何数据）."""
    _require_member(db, workspace_id, current_user)
    items, invalid = await _collect_items(files, paths)
    result = importers.analyze_files(db, workspace_id, current_user, items, parent_id=parent_id)
    result["total_files"] = len(files)
    _merge_skipped(result, invalid, "skipped")
    return result


@router.post("/import/files")
async def import_document_files(
    workspace_id: int,
    files: Annotated[list[UploadFile], File(description="待导入文件（支持文件夹模式的多个文件）")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    paths: Annotated[list[str] | None, Form(description="与 files 一一对应的批次内相对路径")] = None,
    parent_id: Annotated[int | None, Form(description="导入到哪个文件夹（空 = 根目录）")] = None,
    conflict: Annotated[str, Form(description="冲突策略：skip / rename / overwrite")] = CONFLICT_RENAME,
    status: Annotated[str, Form(description="新建文档的状态：draft / published / archived")] = "draft",
    import_attachments: Annotated[bool, Form(description="是否导入 docx / html 内嵌图片")] = True,
) -> dict[str, Any]:
    """把文件批次导入为文档树（文件夹 + 文档 + 附件）."""
    _require_member(db, workspace_id, current_user)
    items, invalid = await _collect_items(files, paths)
    stats = importers.import_files(
        db,
        workspace_id,
        current_user,
        items,
        parent_id=parent_id,
        conflict=conflict,
        status=status,
        import_attachments=import_attachments,
    )
    stats["skipped"] += len(invalid)
    stats["total"] += len(invalid)
    _merge_skipped(stats, invalid, "skipped_files")
    invalidate_document_tree_cache(workspace_id)
    return stats


__all__ = ["router"]

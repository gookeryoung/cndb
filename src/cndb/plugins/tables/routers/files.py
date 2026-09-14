"""附件文件存储路由.

提供上传 / 下载 / 删除三个端点，文件按 workspace 隔离存储在 ``settings.UPLOAD_DIR`` 下::

    {UPLOAD_DIR}/{workspace_id}/{uuid}_{basename}
"""

from __future__ import annotations

import datetime as dt
import mimetypes
import uuid
from pathlib import Path as PathLib
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.routers.tables import _check_table_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/files", tags=["files"])

# 单文件全局上限 50 MB（可按附件字段 config 再限）
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# 允许的扩展名白名单（防上传脚本/可执行文件）
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # 文档
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".md",
        ".csv",
        ".rtf",
        ".odt",
        ".ods",
        ".odp",
        # 图片
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".svg",
        ".ico",
        ".tiff",
        # 音视频
        ".mp3",
        ".wav",
        ".ogg",
        ".mp4",
        ".mov",
        ".avi",
        ".webm",
        # 压缩
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        # 代码
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".py",
        ".js",
        ".ts",
        ".css",
        ".html",
    }
)


def _workspace_dir(workspace_id: int) -> PathLib:
    """返回工作区专属上传目录（自动创建）."""
    d = settings.UPLOAD_DIR / str(workspace_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(filename: str) -> str:
    """将原始文件名安全化（防路径穿越、防超长）."""
    base = PathLib(filename).name  # 去路径，只保留 basename
    # 截断到 200 字符
    return base[:200]


def _file_path(workspace_id: int, file_key: str) -> PathLib:
    """由 file_key 还原出绝对路径（带安全校验，防路径穿越）."""
    # file_key 必须是 uuid.hex + 可选 .ext 格式（不包含路径分隔符、.. 等危险组件）
    if ".." in file_key or "/" in file_key or "\\" in file_key or file_key.startswith("."):
        raise HTTPException(status_code=400, detail="非法的文件标识符")
    if not file_key or len(file_key) > 255:
        raise HTTPException(status_code=400, detail="非法的文件标识符")
    path = _workspace_dir(workspace_id) / file_key
    resolved = path.resolve()
    work_dir = _workspace_dir(workspace_id).resolve()
    if not str(resolved).startswith(str(work_dir) + "/") and resolved != work_dir:
        raise HTTPException(status_code=400, detail="非法的文件标识符")
    return path


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    workspace_id: Annotated[int, Path(...)],
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """上传一个附件文件，返回元数据.

    返回结构可直接作为 ``AttachmentFieldType`` 的单项值::

        {"file_key": "...", "filename": "...", "size": 123, "mime_type": "...", "created_at": "..."}
    """
    # 鉴权：登录即可上传（实际行级权限由 row update 时再校验）
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    safe_name = _safe_filename(file.filename or "unnamed")
    suffix = PathLib(safe_name).suffix.lower()
    if suffix and suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不允许上传扩展名 {suffix!r} 的文件",
        )

    # 读入校验大小
    content = await file.read()
    size = len(content)
    if size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件过大（{size} > {_MAX_UPLOAD_BYTES}）",
        )

    # 生成稳定 file_key: uuid.ext（保留原始扩展名方便识别）
    ext = suffix or ""
    file_key = f"{uuid.uuid4().hex}{ext}"
    target = _file_path(workspace_id, file_key)
    target.write_bytes(content)

    mime = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    return {
        "file_key": file_key,
        "filename": safe_name,
        "size": size,
        "mime_type": mime,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
    }


@router.get("/{file_key}")
def download_file(
    workspace_id: Annotated[int, Path(...)],
    file_key: Annotated[str, Path(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    inline: Annotated[bool, Query()] = False,
) -> FileResponse:
    """下载/预览附件.

    - ``inline=true``：浏览器尝试在标签页内预览（图片、PDF 等）
    - ``inline=false``：强制下载
    """
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    target = _file_path(workspace_id, file_key)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在或已被清理")

    mime, _ = mimetypes.guess_type(file_key)
    media_type = mime or "application/octet-stream"
    disposition = "inline" if inline else "attachment"

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=file_key.split("_", 1)[-1],  # uuid_basename → basename
        headers={"Content-Disposition": disposition},
    )


@router.delete("/{file_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    workspace_id: Annotated[int, Path(...)],
    file_key: Annotated[str, Path(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除附件（只删物理文件；业务层通常在更新行值时同步清理）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    target = _file_path(workspace_id, file_key)
    if target.is_file():
        target.unlink()
    # 文件不存在也静默通过（幂等删除）

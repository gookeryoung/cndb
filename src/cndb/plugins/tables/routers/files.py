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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.files import services as files_service
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import DEFAULT_STORAGE_QUOTA_BYTES, Workspace, WorkspaceRole
from cndb.plugins.workspaces.services.storage import workspace_quota_bytes, workspace_storage_bytes
from cndb.plugins.workspaces.services.storage_snapshot import bump_used_bytes, snapshot_used_bytes

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

# inline 预览时强制改为 attachment（防存储型 XSS：html/svg/xml 可内嵌脚本，
# 浏览器 inline 渲染时会在同源上下文中执行）
_SCRIPTABLE_EXTENSIONS: frozenset[str] = frozenset({".html", ".htm", ".svg", ".xml", ".xhtml", ".xht"})

# 可生成缩略图的图片扩展名（svg 无法用 Pillow 栅格化，走原图）
_THUMBNAILABLE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff"}
)

# 缩略图缓存目录名（放在 UPLOAD_DIR 下的独立子目录，避免和业务文件混在一起；
# file_key 是不可变 uuid，缓存永不失效，删除附件时一并清理）
_THUMB_DIR_NAME = ".thumbs"


def _safe_filename(filename: str) -> str:
    """将原始文件名安全化（防路径穿越、防超长）."""
    base = PathLib(filename).name  # 去路径，只保留 basename
    # 截断到 200 字符
    return base[:200]


def _file_path(workspace_id: int, file_key: str) -> PathLib:
    """由 file_key 还原出绝对路径（路径校验统一走 files_service）."""
    return files_service.resolve_workspace_file(workspace_id, file_key)


def _thumb_cache_path(workspace_id: int, file_key: str, size: int) -> PathLib:
    """缩略图缓存路径：``{UPLOAD_DIR}/.thumbs/{workspace_id}/{file_key}.w{size}.webp``."""
    d = settings.UPLOAD_DIR / _THUMB_DIR_NAME / str(workspace_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{file_key}.w{size}.webp"


def _clear_thumb_cache(workspace_id: int, file_key: str) -> None:
    """删除某文件的全部缩略图缓存（附件被删除时调用；失败静默）."""
    d = settings.UPLOAD_DIR / _THUMB_DIR_NAME / str(workspace_id)
    if not d.is_dir():
        return
    for cached in d.glob(f"{file_key}.w*.webp"):
        cached.unlink(missing_ok=True)


def _generate_thumbnail(source: PathLib, target: PathLib, size: int) -> bool:
    """生成 WebP 缩略图；成功返回 True。Pillow 缺失/解码失败时返回 False（调用方回退原图）."""
    try:
        from PIL import Image, ImageOps  # 运行期才依赖 Pillow（reportlab 已间接安装）
    except ImportError:  # pragma: no cover - 依赖缺失属部署异常
        return False

    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((size, size))
            # 统一到 RGBA 再存 WebP：保留透明通道，避免 PNG logo 变黑底
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            image.save(tmp, format="WEBP", quality=82, method=4)
        tmp.replace(target)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        return False


def _validate_against_field(
    db: Session,
    *,
    field_id: int,
    table_id: int | None,
    filename: str,
    mime: str,
    size: int,
) -> None:
    """按字段配置校验上传（大小 / MIME / 图片类型）.

    上传接口本身拿不到字段，前端在 ``field_id`` 里带上归属字段；后端据此把
    「字段级配置」真正落到上传入口，避免只有前端提示、接口可绕过。
    """
    from cndb.plugins.tables.field_types import AttachmentFieldConfig, ImageFieldConfig
    from cndb.plugins.tables.field_types.files import is_image_meta
    from cndb.plugins.tables.models import DataField

    if table_id is None:
        raise HTTPException(status_code=400, detail="field_id 需要与 table_id 一起使用")

    field = (
        db.query(DataField)
        .filter(
            DataField.id == field_id,
            DataField.table_id == table_id,
            DataField.trashed.is_(False),
        )
        .first()
    )
    if field is None:
        raise HTTPException(status_code=404, detail="字段不存在或已删除")

    if field.field_type == "image" and not is_image_meta({"mime_type": mime, "filename": filename}):
        raise HTTPException(status_code=415, detail=f"字段「{field.name}」只允许上传图片")

    config_cls = {"image": ImageFieldConfig, "attachment": AttachmentFieldConfig}.get(field.field_type)
    if config_cls is None:
        return
    try:
        config = config_cls.model_validate(field.config or {})
    except Exception:
        config = config_cls()

    if config.max_size_mb and size > config.max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件超过字段「{field.name}」限制（{config.max_size_mb} MB）",
        )

    if config.allowed_mime_types:
        actual = mime.lower()
        allowed = [item.lower() for item in config.allowed_mime_types]
        major = actual.split("/")[0] if "/" in actual else ""
        if actual not in allowed and (not major or f"{major}/*" not in allowed):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"文件类型 {mime} 不在字段「{field.name}」允许范围内",
            )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    workspace_id: Annotated[int, Path(...)],
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    table_id: Annotated[int | None, Form()] = None,
    row_id: Annotated[int | None, Form()] = None,
    document_id: Annotated[int | None, Form()] = None,
    field_id: Annotated[int | None, Form()] = None,
) -> dict[str, object]:
    """上传一个附件文件，返回元数据.

    可选 ``table_id`` / ``row_id`` / ``document_id``：登记文件归属，
    使下载与删除按宿主对象（表/行/文档）的权限校验。


    返回结构可直接作为 ``AttachmentFieldType`` 的单项值::

        {"file_key": "...", "filename": "...", "size": 123, "mime_type": "...", "created_at": "..."}
    """
    # 鉴权：至少是工作区成员；带归属时进一步校验对宿主对象的写权限
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    if table_id is not None:
        files_service.assert_can_attach_table(db, table_id=table_id, workspace_id=workspace_id, user=current_user)
    if document_id is not None:
        files_service.assert_can_attach_document(
            db, document_id=document_id, workspace_id=workspace_id, user=current_user
        )

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

    mime = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    # 字段级校验：前端把归属字段 id 一并带上，后端据此校验大小 / MIME / 图片类型，
    # 避免「只有前端提示、直接调接口可绕过字段配置」
    if field_id is not None:
        _validate_against_field(
            db,
            field_id=field_id,
            table_id=table_id,
            filename=safe_name,
            mime=mime,
            size=size,
        )

    # 工作区存储配额：管理员在管理台「空间分配」设定上限（默认 100MB）。
    # 上传前按「已用 + 本次」预判，避免写盘后再回滚。
    # 已用读用量快照（ADR 0024），不在此现算整工作区；快照缺失时懒计算一次，
    # 懒计算失败才退化为现算 —— 配额预判宁慢也不能漏判。
    ws = db.get(Workspace, workspace_id)
    quota = workspace_quota_bytes(ws) if ws is not None else DEFAULT_STORAGE_QUOTA_BYTES
    used = snapshot_used_bytes(db, workspace_id, lazy=True)
    if used is None:
        used = workspace_storage_bytes(db, workspace_id)
    if used + size > quota:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"工作区存储空间不足：已用 {used / (1024 * 1024):.1f} MB / "
                f"配额 {quota / (1024 * 1024):.1f} MB，本次需 {size / (1024 * 1024):.1f} MB"
            ),
        )

    # 生成稳定 file_key: uuid.ext（保留原始扩展名方便识别）
    ext = suffix or ""
    file_key = f"{uuid.uuid4().hex}{ext}"
    target = _file_path(workspace_id, file_key)
    target.write_bytes(content)

    # 记录归属：下载/删除将按宿主对象（表/行/文档）的权限校验
    files_service.record_owner(
        db,
        file_key=file_key,
        workspace_id=workspace_id,
        table_id=table_id,
        row_id=row_id,
        document_id=document_id,
        uploaded_by_id=current_user.id if current_user else None,
    )

    # 用量快照乐观累加（ADR 0024）：连续上传时配额预判立刻反映本次写入，
    # 后台下一轮会重算校正；同时置脏，让该工作区优先进入刷新队列。
    bump_used_bytes(db, workspace_id, size)
    db.commit()

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
    thumb: Annotated[int | None, Query(ge=32, le=1024)] = None,
) -> FileResponse:
    """下载/预览附件.

    - ``inline=true``：浏览器尝试在标签页内预览（图片、PDF 等）；
      对 html/svg/xml 等可脚本化扩展名，为防存储型 XSS 强制改为 attachment 下载。
    - ``inline=false``：强制下载
    - ``thumb=N``：图片按最长边 N（32-1024）返回 WebP 缩略图（磁盘缓存）；
      非图片 / 解码失败时静默回退原图，不影响下载语义。
    """
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    # 按归属校验：受限表 / 未发布文档 / 被行过滤挡掉的行上的附件不可读
    files_service.assert_can_access(db, workspace_id=workspace_id, file_key=file_key, user=current_user)

    target = _file_path(workspace_id, file_key)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在或已被清理")

    # 缩略图：仅对可栅格化图片生效；生成/读取失败时回退原图
    if thumb is not None:
        ext_for_thumb = PathLib(file_key).suffix.lower()
        if ext_for_thumb in _THUMBNAILABLE_EXTENSIONS:
            cache_file = _thumb_cache_path(workspace_id, file_key, thumb)
            if not cache_file.is_file() and not _generate_thumbnail(target, cache_file, thumb):
                cache_file = None
            if cache_file is not None and cache_file.is_file():
                return FileResponse(
                    path=str(cache_file),
                    media_type="image/webp",
                    filename=PathLib(file_key).name,
                    headers={
                        "Content-Disposition": "inline",
                        "Cache-Control": "private, max-age=86400",
                        "X-Content-Type-Options": "nosniff",
                    },
                )

    mime, _ = mimetypes.guess_type(file_key)
    media_type = mime or "application/octet-stream"

    # 防存储型 XSS：可脚本化扩展名一律走 attachment，
    # 即使调用方指定 inline=true 也不内联渲染
    ext = PathLib(file_key).suffix.lower()
    use_inline = inline and ext not in _SCRIPTABLE_EXTENSIONS
    disposition = "inline" if use_inline else "attachment"

    headers = {"Content-Disposition": disposition}
    if not use_inline:
        # 双重保险：nosniff 阻止浏览器基于内容嗅探推断 mime
        headers["X-Content-Type-Options"] = "nosniff"

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=PathLib(file_key).name,  # 直接用 file_key 作为下载名（格式是 uuid.ext）
        headers=headers,
    )


@router.delete("/{file_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    workspace_id: Annotated[int, Path(...)],
    file_key: Annotated[str, Path(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除附件（只删物理文件；业务层通常在更新行值时同步清理）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    # 删除同样按归属校验（与下载一致）
    files_service.assert_can_access(db, workspace_id=workspace_id, file_key=file_key, user=current_user)

    target = _file_path(workspace_id, file_key)
    if target.is_file():
        target.unlink()
    _clear_thumb_cache(workspace_id, file_key)
    files_service.forget_owner(db, file_key)
    # 文件不存在也静默通过（幂等删除）

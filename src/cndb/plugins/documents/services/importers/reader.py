"""通用文件导入读取器：批次校验 + 格式分派 + 逐条隔离（ADR 0010 C4/C8/I5）.

- 单文件模式：批次含 1 条 → 1 篇文档；
- 文件夹模式：批次含多条且带相对路径 → 目录层级映射为文件夹节点（由 importer 完成）。
本模块只负责「读字节 → 转 Markdown」，不触库。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from cndb.core.errors import BadRequestError
from cndb.plugins.documents.services.obsidian import _is_skipped_path, _normalize_entry_path

from . import docx as docx_converter
from . import html as html_converter
from . import markdown as markdown_converter
from . import mhtml as mhtml_converter
from .errors import UnsupportedImport
from .formats import (
    CONTENT_TYPE_IMAGE,
    MAX_ASSET_BYTES,
    SUPPORTED_SUFFIXES,
    asset_format,
    normalize_suffix,
)
from .normalize import clean_title, normalize_markdown

#: 图片落盘回调：(字节, 建议文件名) → 站点文件 key；None 表示不落盘
ImageSink = Callable[[bytes, str], str | None]
#: 批次内本地图片：批次相对路径 → 原始字节（HTML 相对 ``<img src>`` 用）
LocalImages = html_converter.LocalImages

MARKDOWN_SUFFIXES = (".md", ".markdown")
DOCX_SUFFIXES = (".docx",)
HTML_SUFFIXES = (".html", ".htm")
MHTML_SUFFIXES = (".mhtml", ".mht")

MB = 1024 * 1024
#: 单批次文件数上限
MAX_FILES = 500
#: 单文件上限（可转换格式）
MAX_FILE_BYTES = 8 * MB
#: MHTML 单文件上限（图片打包进单文件，放宽到与原件族一致；ADR 0049 D5）
MHTML_MAX_FILE_BYTES = 32 * MB
#: 批次总体积上限
MAX_TOTAL_BYTES = 128 * MB


@dataclass
class UploadedItem:
    """一条上传文件：批次内相对路径 + 原始字节."""

    path: str
    data: bytes


@dataclass
class ImportedDoc:
    """转换结果：标题 + 规整后的 Markdown 正文，或原件族标记（ADR 0025）.

    ``asset=True`` 表示该条不做 Markdown 转换：正文为空，原件由调用方落盘，
    文档节点按 ``content_type`` / ``mime`` 标记格式。
    ``resources``：MHTML 图片素材 ``[(相对路径, 字节)]``（ADR 0049），关态由调用方展开。
    """

    path: str
    title: str
    body: str
    suffix: str
    warnings: list[str] = field(default_factory=list)
    asset: bool = False
    content_type: str = "markdown"
    mime: str = ""
    resources: list[tuple[str, bytes]] = field(default_factory=list)


def is_supported(path: str) -> bool:
    """扩展名是否在支持清单内（可转换 + 原件族，见 ``formats``）."""
    return normalize_suffix(path) in SUPPORTED_SUFFIXES


def normalize_path(raw: str) -> str | None:
    """上传相对路径归一化；非法 / 隐藏项返回 None（复用 Obsidian 通道口径）."""
    path = _normalize_entry_path(raw)
    if path is None or _is_skipped_path(path):
        return None
    return path


def validate_batch(items: Iterable[UploadedItem]) -> int:
    """批次级校验：非空 + 条目数上限 + 总体积上限；超限抛 ``BadRequestError``.

    单文件超限不在此处拦截（由 ``convert_file`` 记为首条 skip，不中断整批）。
    返回批次总字节数。
    """
    items = list(items)
    if not items:
        raise BadRequestError("没有收到任何文件")
    if len(items) > MAX_FILES:
        raise BadRequestError(f"一次最多导入 {MAX_FILES} 个文件（当前 {len(items)}）")
    total = sum(len(item.data) for item in items)
    if total > MAX_TOTAL_BYTES:
        raise BadRequestError(f"批次总体积过大（{total // MB}MB > {MAX_TOTAL_BYTES // MB}MB）")
    return total


def build_local_image_index(items: Iterable[UploadedItem]) -> dict[str, bytes]:
    """批次内图片文件按归一化路径索引（供 HTML 相对 ``<img src>`` 内联）."""
    index: dict[str, bytes] = {}
    for item in items:
        fmt = asset_format(item.path)
        if fmt is not None and fmt.content_type == CONTENT_TYPE_IMAGE and item.data:
            index[item.path] = item.data
    return index


def convert_file(
    item: UploadedItem,
    *,
    image_sink: ImageSink | None = None,
    local_images: LocalImages | None = None,
) -> ImportedDoc:
    """分派单个文件；不支持 / 损坏 / 超限时抛 ``UnsupportedImport``.

    原件族（PDF / Office / 图片）不转换，返回 ``asset=True`` 的结果，由 importer 落盘。
    ``local_images`` 供 HTML 把同批上传的相对路径图片内联为站内附件。
    """
    suffix = normalize_suffix(item.path)
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedImport(f"不支持的格式：{suffix or '无扩展名'}")
    if not item.data:
        raise UnsupportedImport("文件为空")

    fmt = asset_format(item.path)
    if fmt is not None:
        return _convert_asset(item, suffix, fmt.content_type, fmt.mime)

    if suffix in MHTML_SUFFIXES:
        # MHTML 单独放宽到 32MB（图片打包进单文件，ADR 0049 D5），先于通用 8MB 检查
        if len(item.data) > MHTML_MAX_FILE_BYTES:
            raise UnsupportedImport(f"MHTML 文件超过 {MHTML_MAX_FILE_BYTES // MB}MB")
        try:
            title, body, warnings, resources = mhtml_converter.convert_mhtml(
                item.data, item.path, image_sink=image_sink
            )
        except UnsupportedImport:
            raise
        except Exception as exc:
            raise UnsupportedImport(f"解析失败：{exc}") from exc
        return ImportedDoc(
            path=item.path,
            title=clean_title(title or Path(item.path).stem),
            body=normalize_markdown(body),
            suffix=suffix,
            warnings=warnings,
            resources=resources,
        )

    if len(item.data) > MAX_FILE_BYTES:
        raise UnsupportedImport(f"文件超过 {MAX_FILE_BYTES // MB}MB")
    try:
        if suffix in MARKDOWN_SUFFIXES:
            title, body, warnings = markdown_converter.convert_markdown(item.data, item.path)
        elif suffix in DOCX_SUFFIXES:
            title, body, warnings = docx_converter.convert_docx(item.data, item.path, image_sink=image_sink)
        else:
            title, body, warnings = html_converter.convert_html(
                item.data, item.path, image_sink=image_sink, local_images=local_images
            )
    except UnsupportedImport:
        raise
    except Exception as exc:
        raise UnsupportedImport(f"解析失败：{exc}") from exc
    return ImportedDoc(
        path=item.path,
        title=clean_title(title or Path(item.path).stem),
        body=normalize_markdown(body),
        suffix=suffix,
        warnings=warnings,
    )


def _convert_asset(item: UploadedItem, suffix: str, content_type: str, mime: str) -> ImportedDoc:
    """原件族：只做体积校验，标题取文件名（原件不解析、不转换）."""
    if len(item.data) > MAX_ASSET_BYTES:
        raise UnsupportedImport(f"文件超过 {MAX_ASSET_BYTES // MB}MB")
    return ImportedDoc(
        path=item.path,
        title=clean_title(Path(item.path).stem),
        body="",
        suffix=suffix,
        asset=True,
        content_type=content_type,
        mime=mime,
    )


def convert_batch(
    items: Iterable[UploadedItem], *, image_sink: ImageSink | None = None
) -> tuple[list[ImportedDoc], list[dict[str, str]]]:
    """逐条转换（单条失败只记 skip，不中断整批），返回 ``(成功项, 跳过明细)``.

    批次内图片先建索引，HTML 相对 ``<img src>`` 才能内联为站内附件。
    """
    batch = list(items)
    local_images = build_local_image_index(batch)
    docs: list[ImportedDoc] = []
    skipped: list[dict[str, str]] = []
    for item in batch:
        try:
            docs.append(convert_file(item, image_sink=image_sink, local_images=local_images))
        except UnsupportedImport as exc:
            skipped.append({"path": item.path, "reason": str(exc)})
    return docs, skipped


__all__ = [
    "DOCX_SUFFIXES",
    "HTML_SUFFIXES",
    "MARKDOWN_SUFFIXES",
    "MAX_FILES",
    "MAX_TOTAL_BYTES",
    "MHTML_MAX_FILE_BYTES",
    "MHTML_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "ImageSink",
    "ImportedDoc",
    "LocalImages",
    "UnsupportedImport",
    "UploadedItem",
    "build_local_image_index",
    "convert_batch",
    "convert_file",
    "is_supported",
    "normalize_path",
    "validate_batch",
]

"""导入格式注册表：扩展名 → 处理方式 / 内容类型 / MIME（ADR 0025）.

分两类：

- **可转换**（``CONVERTIBLE_SUFFIXES``）：md / docx / html，走 ADR 0010 的
  「源格式 → Markdown」转换管线，落库后 ``content_type = markdown``；
- **原件族**（``ASSET_FORMATS``）：PDF / Office / 图片，无法可靠转成 Markdown，
  **原样存档**（原件进上传目录，文档节点记录格式与 MIME），正文走阅读器。

新增格式只改本文件：``reader`` 的扩展名白名单与 ``importer`` 的落库分派都读这张表。
"""

from __future__ import annotations

from dataclasses import dataclass

from cndb.plugins.documents.models import (
    ASSET_CONTENT_TYPES,
    CONTENT_TYPE_IMAGE,
    CONTENT_TYPE_MHTML,
    CONTENT_TYPE_PDF,
    CONTENT_TYPE_PPTX,
    CONTENT_TYPE_XLSX,
)

#: 一次能可靠转成 Markdown 的源格式（ADR 0010；MHTML 见 ADR 0049）
CONVERTIBLE_SUFFIXES = (".md", ".markdown", ".docx", ".html", ".htm", ".mhtml", ".mht")


@dataclass(frozen=True)
class AssetFormat:
    """原件格式：渲染族 + 权威 MIME + 展示名."""

    content_type: str
    mime: str
    label: str


#: 原件族扩展名 → 格式（顺序即前端展示顺序：文档 / 表格 / 演示 / 图片）
ASSET_FORMATS: dict[str, AssetFormat] = {
    ".pdf": AssetFormat(CONTENT_TYPE_PDF, "application/pdf", "PDF"),
    ".xlsx": AssetFormat(
        CONTENT_TYPE_XLSX,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Excel",
    ),
    ".xls": AssetFormat(CONTENT_TYPE_XLSX, "application/vnd.ms-excel", "Excel"),
    ".pptx": AssetFormat(
        CONTENT_TYPE_PPTX,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "PowerPoint",
    ),
    ".ppt": AssetFormat(CONTENT_TYPE_PPTX, "application/vnd.ms-powerpoint", "PowerPoint"),
    ".png": AssetFormat(CONTENT_TYPE_IMAGE, "image/png", "图片"),
    ".jpg": AssetFormat(CONTENT_TYPE_IMAGE, "image/jpeg", "图片"),
    ".jpeg": AssetFormat(CONTENT_TYPE_IMAGE, "image/jpeg", "图片"),
    ".gif": AssetFormat(CONTENT_TYPE_IMAGE, "image/gif", "图片"),
    ".webp": AssetFormat(CONTENT_TYPE_IMAGE, "image/webp", "图片"),
    ".svg": AssetFormat(CONTENT_TYPE_IMAGE, "image/svg+xml", "图片"),
    ".bmp": AssetFormat(CONTENT_TYPE_IMAGE, "image/bmp", "图片"),
}

#: 全量白名单：可转换 + 原件族
SUPPORTED_SUFFIXES: tuple[str, ...] = CONVERTIBLE_SUFFIXES + tuple(ASSET_FORMATS)

#: 原件单文件上限（图片 / PDF 普遍大于文本上限）
MAX_ASSET_BYTES = 32 * 1024 * 1024

#: MHTML 处理模式（0061）：archive=原样存档（默认），convert=转 Markdown（ADR 0049 链路）
MHTML_MODES = ("convert", "archive")
MHTML_MODE_DEFAULT = "archive"
#: archive 模式的原件格式标记（MHTML 不进 ``ASSET_FORMATS``：convert 模式仍走转换管线）
MHTML_ASSET_FORMAT = AssetFormat(CONTENT_TYPE_MHTML, "multipart/related", "MHTML")


def normalize_suffix(path: str) -> str:
    """取小写扩展名（含点）；无扩展名返回空串。"""
    dot = path.rfind(".")
    slash = path.rfind("/")
    backslash = path.rfind("\\")
    if dot <= max(slash, backslash):
        return ""
    return path[dot:].lower()


def asset_format(path: str) -> AssetFormat | None:
    """查原件格式；非原件族返回 None."""
    return ASSET_FORMATS.get(normalize_suffix(path))


def is_convertible(path: str) -> bool:
    return normalize_suffix(path) in CONVERTIBLE_SUFFIXES


def is_supported(path: str) -> bool:
    return normalize_suffix(path) in SUPPORTED_SUFFIXES


__all__ = [
    "ASSET_CONTENT_TYPES",
    "ASSET_FORMATS",
    "CONTENT_TYPE_IMAGE",
    "CONTENT_TYPE_MHTML",
    "CONTENT_TYPE_PDF",
    "CONTENT_TYPE_PPTX",
    "CONTENT_TYPE_XLSX",
    "CONVERTIBLE_SUFFIXES",
    "MAX_ASSET_BYTES",
    "MHTML_ASSET_FORMAT",
    "MHTML_MODES",
    "MHTML_MODE_DEFAULT",
    "SUPPORTED_SUFFIXES",
    "AssetFormat",
    "asset_format",
    "is_convertible",
    "is_supported",
    "normalize_suffix",
]

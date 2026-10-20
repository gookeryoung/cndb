"""documents 插件通用文件导入包（md / docx / html，单文件与文件夹模式）.

- ``reader``：批次校验 + 格式分派 + 逐条隔离（返回 ImportedDoc）
- ``normalize``：标题清洗 / 正文空白规整 / 文本解码
- ``markdown`` / ``docx`` / ``html``：各源格式 → Markdown 转换器
- ``importer``：预览（只读）与落库编排（文件夹 / 冲突 / 附件 / 权限）
"""

from __future__ import annotations

from . import docx, errors, html, importer, markdown, normalize, reader
from .errors import UnsupportedImport
from .importer import analyze_files, import_files
from .reader import (
    ImportedDoc,
    UploadedItem,
    convert_batch,
    convert_file,
    is_supported,
    normalize_path,
    validate_batch,
)

__all__ = [
    "ImportedDoc",
    "UnsupportedImport",
    "UploadedItem",
    "analyze_files",
    "convert_batch",
    "convert_file",
    "docx",
    "errors",
    "html",
    "import_files",
    "importer",
    "is_supported",
    "markdown",
    "normalize",
    "normalize_path",
    "reader",
    "validate_batch",
]

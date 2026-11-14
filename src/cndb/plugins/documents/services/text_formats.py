"""纯文本族扩展名清单（需求 0135 / 需求 0010 C9）：单文件导入与压缩包导入共用.

放在中性模块里（不放 ``importers`` 包内）：``services.obsidian``（压缩包通道）也要引用，
而 ``importers`` 包的 ``__init__`` 会反向导入 ``obsidian``，从 ``obsidian`` 直接 import
``importers.formats`` 会形成循环。

口径：文本族按**原文**读入为 Markdown 正文——不解码语义以外的转换、不转义、不做
空白重排，避免破坏日志 / 配置 / CSV 的对齐与结构；标题取文件名（去扩展名）。
"""

from __future__ import annotations

#: 纯文本族：内容本身就是可读文本，只做编码兜底与换行统一
TEXT_SUFFIXES: tuple[str, ...] = (
    ".txt",
    ".text",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".ini",
    ".conf",
    ".properties",
    ".rst",
)

__all__ = ["TEXT_SUFFIXES"]

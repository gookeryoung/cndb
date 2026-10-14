"""各渲染器共用的 Markdown 风格行内/块级正则。

GFM 表格分隔行参考 https://github.github.com/gfm/#tables-extension- 。"""

from __future__ import annotations

import re

# Markdown 风格标题 / 粗体正则
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
# GFM 表格分隔行：至少 1 个短横线（允许前后各一个冒号表示对齐）
# 参考 https://github.github.com/gfm/#tables-extension-
_MD_TABLE_SEP_RE = re.compile(r"^:?-{1,}:?$")

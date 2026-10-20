"""Markdown 正文与标题规整：清理多余空白，同时不破坏 Markdown 语义（ADR 0010 I3）.

设计要点（对应需求 C7，保守清理边界）：

- 只清「行尾空白」「行内连续空格」「连续空行」「无效行首缩进」四类；
- **不改动**代码围栏（``` / ~~~）内、front-matter 内、表格行内的空白（会破坏语义）；
- **不删**中文与英文/数字之间的空格（误伤风险高）；
- 行内反引号代码跨度（`` ` ``）内的空白原样保留。
"""

from __future__ import annotations

import re
import unicodedata

#: 代码围栏起始/结束行（0~3 空格缩进）
_FENCE_RE = re.compile(r"^[ \t]{0,3}(?:```|~~~)")
#: 表格行（以 ``|`` 起头）
_TABLE_ROW_RE = re.compile(r"^[ \t]*\|")
#: 列表项标记
_LIST_MARKER_RE = re.compile(r"(?:[-*+]|\d{1,9}[.)])(?=[ \t])")
#: front-matter 块（``---`` 包裹，仅取文件开头）
_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
#: 行内连续空白
_INLINE_SPACE_RE = re.compile(r"[ \t]{2,}")
#: 任意空白（用于文本折叠）
_ANY_SPACE_RE = re.compile(r"\s+")
#: 缩进视为「代码缩进」的阈值
_CODE_INDENT = 4
#: 标题长度上限（对齐 ``Document.title``）
_TITLE_MAX = 500


def decode_text(data: bytes) -> str:
    """把文本字节流解码为字符串：常见编码优先，chardet 兜底，最终 latin-1 替换.

    兜底策略保证任何字节流都能得到字符串（不抛错），符合「单条隔离、整批不中断」。
    """
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    import chardet

    detection = chardet.detect(data)
    detected = (detection.get("encoding") or "").strip()
    confidence = float(detection.get("confidence") or 0.0)
    if detected and detected.lower() != "ascii" and confidence >= 0.5:
        try:
            return data.decode(detected)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("latin-1", errors="replace")


def clean_title(raw: str, *, fallback: str = "未命名") -> str:
    """标题清洗：NFKC 归一 + 去控制字符 + 折叠空白 + 截断到 500.

    与既有 ``obsidian._clean_title`` 口径一致，保证不同导入通道标题表现统一。
    """
    text = unicodedata.normalize("NFKC", raw or "").replace("\x00", "").strip()
    text = _ANY_SPACE_RE.sub(" ", text)
    return text[:_TITLE_MAX] or fallback


def collapse_whitespace(text: str) -> str:
    """把任意连续空白（含换行）折叠为单个空格（用于 HTML 文本节点）."""
    return _ANY_SPACE_RE.sub(" ", text)


def collapse_inline_spaces(text: str) -> str:
    """折叠行内连续空格，但保留反引号代码跨度内的原样空白."""
    parts = text.split("`")
    for index in range(0, len(parts), 2):
        parts[index] = _INLINE_SPACE_RE.sub(" ", parts[index])
    return "`".join(parts)


def _is_table_row(line: str) -> bool:
    return _TABLE_ROW_RE.match(line) is not None


def _clean_body_line(line: str) -> str:
    """规整单行正文：去行尾空白 + 折叠行内空格 + 清理无效缩进（调用方保证非空行）."""
    stripped = line.rstrip()
    if _is_table_row(stripped):
        # 表格行保持列内空白，仅去行尾
        return stripped
    indent_len = len(stripped) - len(stripped.lstrip(" \t"))
    indent = stripped[:indent_len]
    rest = collapse_inline_spaces(stripped[indent_len:]).rstrip()
    # 列表项 / 引用 / 4 空格以上的代码缩进 → 保留缩进；否则视为无效缩进剔除
    keep_indent = bool(_LIST_MARKER_RE.match(rest)) or rest.startswith(">") or len(indent.expandtabs(4)) >= _CODE_INDENT
    return (indent if keep_indent else "") + rest


def _split_front_matter(text: str) -> tuple[list[str], str]:
    """分离文件开头的 front-matter，返回 ``(front 行, 其余正文)``."""
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        return [], text
    front_lines = text[: match.end()].rstrip("\n").split("\n")
    return front_lines, text[match.end() :]


def normalize_markdown(text: str) -> str:
    """正文规整入口：返回清理多余空白后的 Markdown.

    - 换行统一为 ``\\n``；
    - 连续空行折叠为至多一个空行（代码围栏内原样保留）；
    - 行尾空白剔除、行内连续空格折叠（围栏 / 表格 / front-matter 除外）；
    - 无效行首缩进剔除；
    - 文末多余空行剔除。
    """
    if not text or not text.strip():
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    front_lines, body = _split_front_matter(text)
    out: list[str] = list(front_lines)
    in_fence = False
    pending_blank = False
    for line in body.split("\n"):
        if in_fence:
            if _FENCE_RE.match(line):
                in_fence = False
                out.append(line.rstrip())
            else:
                # 围栏内原样保留（含空行与行尾空白）
                out.append(line)
            continue
        if _FENCE_RE.match(line):
            if pending_blank and out and out[-1].strip():
                out.append("")
            pending_blank = False
            in_fence = True
            out.append(line.rstrip())
            continue
        if not line.strip():
            pending_blank = True
            continue
        if pending_blank and out and out[-1].strip():
            out.append("")
        pending_blank = False
        out.append(_clean_body_line(line))
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


__all__ = ["clean_title", "collapse_inline_spaces", "collapse_whitespace", "decode_text", "normalize_markdown"]

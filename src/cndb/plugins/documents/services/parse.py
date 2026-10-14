"""Markdown 轻量解析服务：front-matter / TOC / 摘要 / slug.

不引入外部 Markdown 库（项目依赖保持精简），仅做结构提取：
- YAML front-matter（``---`` 包裹的简单 ``key: value``）
- 目录树（标题行扫描，# ~ ######）
- 摘要（首个非标题、非代码段落截断）
- slug 生成（标题 → URL 友好串）
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMphasis_RE = re.compile(r"(\*\*|__|\*|_|`|~~)")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


def parse_front_matter(content: str) -> tuple[dict[str, str], str]:
    """解析 YAML front-matter，返回 (元数据字典, 去除 front-matter 后的正文).

    仅支持简单 ``key: value`` 行（不做完整 YAML 解析）。
    """
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        return {}, content

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, content[match.end() :]


def extract_toc(content: str) -> list[dict[str, Any]]:
    """提取标题目录树（扁平列表，带 level 供前端缩进）.

    Returns:
        [{"level": 1, "text": "标题", "line": 3}, ...]
    """
    toc: list[dict[str, Any]] = []
    in_fence = False
    for line_no, line in enumerate(content.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            toc.append({"level": len(m.group(1)), "text": m.group(2).strip(), "line": line_no})
    return toc


def extract_summary(content: str, max_len: int = 200) -> str:
    """提取摘要：首个非标题/非代码块段落，截断到 max_len 字符."""
    meta, body = parse_front_matter(content)
    if "summary" in meta:
        return meta["summary"][:max_len]

    in_fence = False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or _HEADING_RE.match(line):
            continue
        text = line.strip()
        if not text or text.startswith((">", "-", "*", "+", "|", "```")):
            continue
        # 剥离行内标记
        text = _IMG_RE.sub("", text)
        text = _LINK_RE.sub(r"\1", text)
        text = _EMphasis_RE.sub("", text)
        text = text.strip()
        if text:
            return text[:max_len]
    return ""


def extract_author(content: str) -> str:
    """从 front-matter 提取作者（author/author_id 键）."""
    meta, _ = parse_front_matter(content)
    return str(meta.get("author", meta.get("author_id", "")))[:200]


def generate_slug(title: str, doc_id: int | None = None) -> str:
    """生成 URL 友好 slug：ASCII 化标题 + 短哈希，保证唯一性.

    中文标题 unicode 化后保留，非法字符替换为 -。
    """
    text = unicodedata.normalize("NFKC", title).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip("-")[:80]
    digest = hashlib.sha1(f"{title}:{doc_id}".encode()).hexdigest()[:8]
    return f"{text or 'doc'}-{digest}"


def extract_wikilinks(content: str) -> list[str]:
    """提取双向链接 ``[[文档标题]]`` 引用的标题列表（保持出现顺序，去重）.

    代码围栏内的 ``[[...]]`` 视为字面文本，不参与解析。
    """
    titles: list[str] = []
    seen: set[str] = set()
    in_fence = False
    for line in content.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _WIKILINK_RE.finditer(line):
            title = m.group(1).strip()
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
    return titles


def content_hash(content: str) -> str:
    """内容 SHA256（用于版本去重判断）."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def unified_diff(base: str, head: str, context_lines: int = 3) -> tuple[str, int, int]:
    """计算两版本 unified diff.

    Returns:
        (diff 文本, 新增行数, 删除行数)
    """
    import difflib

    base_lines = base.splitlines(keepends=True)
    head_lines = head.splitlines(keepends=True)
    diff_gen = difflib.unified_diff(base_lines, head_lines, fromfile="base", tofile="head", n=context_lines)
    diff_text = "".join(diff_gen)
    added = sum(1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return diff_text, added, removed


__all__ = [
    "content_hash",
    "extract_author",
    "extract_summary",
    "extract_toc",
    "extract_wikilinks",
    "generate_slug",
    "parse_front_matter",
    "unified_diff",
]

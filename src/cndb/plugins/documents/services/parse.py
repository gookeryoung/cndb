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

#: 单篇正文最多解析的双链条数（防极端正文拖慢出链/反链）
_MAX_WIKILINKS = 2000


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


def parse_wikilink(inner: str) -> dict[str, str]:
    """解析双链内层文本 ``目标#锚点|别名``，返回 ``{target, anchor, alias, raw}``.

    三种成分都可缺省：``[[目标]]`` / ``[[目标#锚点]]`` / ``[[目标|别名]]`` /
    ``[[目标#锚点|别名]]``。``target`` 为空表示本文内锚点（``[[#标题]]``）。
    """
    text = (inner or "").strip()
    body, sep, alias = text.partition("|")
    target, hash_sep, anchor = body.partition("#")
    return {
        "target": target.strip(),
        "anchor": anchor.strip() if hash_sep else "",
        "alias": alias.strip() if sep else "",
        "raw": f"[[{text}]]",
    }


def format_wikilink(target: str, *, anchor: str = "", alias: str = "") -> str:
    """把三段成分拼回双链原文（锚点/别名按需保留）."""
    inner = target
    if anchor:
        inner += f"#{anchor}"
    if alias:
        inner += f"|{alias}"
    return f"[[{inner}]]"


def iter_wikilinks(content: str) -> list[dict[str, str]]:
    """逐条提取双链（保持出现顺序，按原文去重；数量有上限防极端正文）.

    代码围栏内的 ``[[...]]`` 视为字面文本，不参与解析。
    """
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    in_fence = False
    for line in content.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _WIKILINK_RE.finditer(line):
            parsed = parse_wikilink(m.group(1))
            if not parsed["raw"] or parsed["raw"] in seen or not (parsed["target"] or parsed["anchor"]):
                continue
            seen.add(parsed["raw"])
            links.append(parsed)
            if len(links) >= _MAX_WIKILINKS:
                return links
    return links


def extract_wikilinks(content: str) -> list[str]:
    """提取双向链接的目标标题列表（保持出现顺序，去重）.

    ``[[目标#锚点|别名]]`` 只取 ``目标``；``[[#本文锚点]]``（目标为空）不计入。
    代码围栏内的 ``[[...]]`` 视为字面文本，不参与解析。
    """
    titles: list[str] = []
    seen: set[str] = set()
    for link in iter_wikilinks(content):
        target = link["target"]
        if target and target not in seen:
            seen.add(target)
            titles.append(target)
    return titles


def rewrite_wikilink_target(content: str, old: str, new: str) -> tuple[str, int]:
    """把正文中所有目标为 ``old`` 的双链改指 ``new``，保留原有锚点与别名.

    Returns:
        (新正文, 替换处数)。代码围栏内的内容不改动。
    """
    if not old or old == new:
        return content, 0
    replaced = 0
    in_fence = False
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        def _sub(match: re.Match[str]) -> str:
            nonlocal replaced
            parsed = parse_wikilink(match.group(1))
            if parsed["target"] != old:
                return match.group(0)
            replaced += 1
            return format_wikilink(new, anchor=parsed["anchor"], alias=parsed["alias"])

        out.append(_WIKILINK_RE.sub(_sub, line))
    return "".join(out), replaced


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
    "format_wikilink",
    "generate_slug",
    "iter_wikilinks",
    "parse_front_matter",
    "parse_wikilink",
    "rewrite_wikilink_target",
    "unified_diff",
]

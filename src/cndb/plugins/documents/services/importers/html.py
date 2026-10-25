"""HTML → Markdown 转换：基于标准库 ``html.parser`` 构建轻量 DOM 后渲染.

支持的块级元素：h1-h6 / p / ul / ol / li / blockquote / pre / table / hr / div 容器；
行内元素：a / strong / b / em / i / del / code / br / img。
``<script>`` / ``<style>`` 等非正文内容丢弃；``<title>`` 或首个 ``<h1>`` 作为标题并从正文剥离。
图片：``data:`` URI 经 ``image_sink`` 落盘为站内附件，外链图片保留原 URL（决策 D2）。
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import override

from .errors import UnsupportedImport
from .normalize import collapse_whitespace, decode_text

#: 图片落盘回调：(字节, 建议文件名) → 站点文件 key；None 表示不落盘
ImageSink = Callable[[bytes, str], str | None]

_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "iframe", "svg", "template", "canvas"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_CONTAINERS = frozenset(
    {
        "#root",
        "html",
        "body",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "nav",
        "figure",
        "figcaption",
        "form",
        "fieldset",
        "details",
        "summary",
        "dl",
        "dt",
        "dd",
        "center",
        "address",
    }
)
_CELL_TAGS = frozenset({"td", "th"})
_MIME_SUFFIX = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


@dataclass(eq=False)
class _Node:
    """轻量 DOM 节点（``eq=False`` 保证可用对象身份做集合成员判断）."""

    tag: str
    attrs: dict[str, str]
    children: list[_Node | str]


class _Builder(HTMLParser):
    """把 HTML 文本解析为 ``_Node`` 树（容忍未闭合与错序标签）."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, [])
        self._stack: list[_Node] = [self.root]

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): (value or "") for key, value in attrs}, [])
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    @override
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): (value or "") for key, value in attrs}, [])
        self._stack[-1].children.append(node)

    @override
    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _VOID_TAGS:
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    @override
    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


@dataclass
class _Ctx:
    """渲染上下文：图片落盘回调 + 告警收集 + 图片计数."""

    sink: ImageSink | None = None
    warnings: list[str] = field(default_factory=list)
    images: int = 0


def _walk(node: _Node) -> Iterator[_Node]:
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _walk(child)


def _node_text(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        parts.append(child if isinstance(child, str) else _node_text(child))
    return "".join(parts)


def _find_first(root: _Node, tag: str) -> _Node | None:
    for node in _walk(root):
        if node.tag == tag:
            return node
    return None


def _decode_data_uri(uri: str) -> tuple[bytes, str] | None:
    """解析 ``data:`` URI，返回 ``(字节, 后缀)``；非 base64 或损坏返回 None."""
    header, _, payload = uri.partition(",")
    if not payload or ";base64" not in header.lower():
        return None
    try:
        data = base64.b64decode(payload)
    except (ValueError, binascii.Error):
        return None
    mime = header[len("data:") :].split(";", 1)[0].strip().lower()
    suffix = _MIME_SUFFIX.get(mime)
    if suffix is None:
        suffix = f".{mime.split('/')[-1]}" if mime.startswith("image/") and "/" in mime else ".bin"
    return data, suffix


def _image_markdown(node: _Node, ctx: _Ctx) -> str:
    """``<img>`` → Markdown：data URI 落盘引用，外链保留原 URL."""
    src = (node.attrs.get("src") or "").strip()
    alt = (node.attrs.get("alt") or "").strip()
    if not src:
        return ""
    if not src.lower().startswith("data:"):
        return f"![{alt}]({src})"
    decoded = _decode_data_uri(src)
    if decoded is None:
        ctx.warnings.append("data URI 图片无法解析，已跳过")
        return f"_[图片未导入：{alt or 'image'}]_"
    ctx.images += 1
    name = f"image{ctx.images}{decoded[1]}"
    if ctx.sink is not None:
        key = ctx.sink(decoded[0], name)
        if key:
            return f"![{alt or name}](file:{key})"
    ctx.warnings.append(f"内嵌图片未导入：{name}")
    return f"_[图片未导入：{name}]_"


def _inline(node: _Node | str, ctx: _Ctx) -> str:
    """行内渲染：返回单行 Markdown 片段（块级元素在此处退化为纯文本）."""
    if isinstance(node, str):
        return collapse_whitespace(node)
    tag = node.tag
    if tag in _SKIP_TAGS:
        return ""
    if tag == "br":
        return "\n"
    if tag == "img":
        return _image_markdown(node, ctx)
    if tag == "code":
        raw = _node_text(node).strip()
        return f"`{raw}`" if raw else ""
    inner = "".join(_inline(child, ctx) for child in node.children)
    stripped = inner.strip()
    if not stripped:
        return ""
    if tag in ("strong", "b"):
        return f"**{stripped}**"
    if tag in ("em", "i"):
        return f"*{stripped}*"
    if tag in ("del", "s", "strike"):
        return f"~~{stripped}~~"
    if tag == "a":
        href = (node.attrs.get("href") or "").strip()
        return f"[{stripped}]({href})" if href else stripped
    return inner


def _render_list(node: _Node, ctx: _Ctx, *, ordered: bool, indent: int = 0) -> list[str]:
    """列表 → Markdown 行（嵌套列表按两级空格缩进）."""
    lines: list[str] = []
    index = 0
    for child in node.children:
        if not isinstance(child, _Node) or child.tag != "li":
            continue
        index += 1
        parts: list[str] = []
        nested: list[_Node] = []
        for sub in child.children:
            if isinstance(sub, _Node) and sub.tag in ("ul", "ol"):
                nested.append(sub)
            else:
                parts.append(_inline(sub, ctx))
        text = " ".join(part.strip() for part in parts if part.strip())
        marker = f"{index}." if ordered else "-"
        lines.append("  " * indent + marker + (f" {text}" if text else ""))
        for sub in nested:
            lines.extend(_render_list(sub, ctx, ordered=sub.tag == "ol", indent=indent + 1))
    return lines


def _code_block(node: _Node) -> str:
    """``<pre>`` → 围栏代码块（语言取自 ``<code class="language-x">``）."""
    code = _find_first(node, "code")
    source = code if code is not None else node
    raw = _node_text(source).strip("\n")
    language = ""
    if code is not None:
        for token in (code.attrs.get("class") or "").split():
            if token.startswith("language-"):
                language = token[len("language-") :]
    return f"```{language}\n{raw}\n```"


def _cell_markdown(cell: _Node, ctx: _Ctx) -> str:
    text = collapse_whitespace("".join(_inline(child, ctx) for child in cell.children)).strip()
    return text.replace("|", "\\|")


def _table_markdown(node: _Node, ctx: _Ctx) -> str:
    rows: list[list[str]] = []
    for child in _walk(node):
        if child.tag != "tr":
            continue
        cells = [_cell_markdown(cell, ctx) for cell in child.children if isinstance(cell, _Node) and cell.tag in _CELL_TAGS]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    lines = ["| " + " | ".join(rows[0] + [""] * (width - len(rows[0]))) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row + [""] * (width - len(row))) + " |")
    return "\n".join(lines)


def _blocks(node: _Node, ctx: _Ctx, *, skip: set[_Node]) -> list[str]:
    """块级渲染：返回 Markdown 块列表（调用方以空行拼接）."""
    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        text = "".join(buffer).strip()
        buffer.clear()
        if text:
            out.append(text)

    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                buffer.append(collapse_whitespace(child))
            continue
        if child in skip or child.tag in _SKIP_TAGS:
            continue
        tag = child.tag
        if tag in _HEADING_TAGS:
            flush()
            text = _inline(child, ctx).strip()
            if text:
                out.append("#" * int(tag[1]) + " " + text)
        elif tag == "p":
            flush()
            text = _inline(child, ctx).strip()
            if text:
                out.append(text)
        elif tag in ("ul", "ol"):
            flush()
            out.extend(_render_list(child, ctx, ordered=tag == "ol"))
        elif tag == "blockquote":
            flush()
            inner = _blocks(child, ctx, skip=skip)
            if inner:
                out.append("\n".join("> " + line if line else ">" for block in inner for line in block.split("\n")))
        elif tag == "pre":
            flush()
            out.append(_code_block(child))
        elif tag == "hr":
            flush()
            out.append("---")
        elif tag == "table":
            flush()
            markdown = _table_markdown(child, ctx)
            if markdown:
                out.append(markdown)
        elif tag == "br":
            buffer.append("\n")
        elif tag in _BLOCK_CONTAINERS or tag in ("li", "td", "th", "tr"):
            flush()
            out.extend(_blocks(child, ctx, skip=skip))
        else:
            buffer.append(_inline(child, ctx))
    flush()
    return out


def convert_html(data: bytes, path: str, *, image_sink: ImageSink | None = None) -> tuple[str, str, list[str]]:
    """把 ``.html`` / ``.htm`` 字节流转换为 ``(标题, 正文 Markdown, 告警)``.

    标题优先级：``<title>`` → 首个 ``<h1>``（并从正文剥离）→ 文件名。
    """
    text = decode_text(data)
    if not text.strip():
        raise UnsupportedImport("HTML 文件为空")
    parser = _Builder()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # 交由调用方按「单条跳过」处理
        raise UnsupportedImport("无法解析 HTML 文件") from exc

    ctx = _Ctx(sink=image_sink)
    skip: set[_Node] = set()
    title = ""
    title_node = _find_first(parser.root, "title")
    if title_node is not None:
        skip.add(title_node)
        title = collapse_whitespace(_node_text(title_node)).strip()
    if not title:
        heading = _find_first(parser.root, "h1")
        if heading is not None:
            heading_text = collapse_whitespace(_node_text(heading)).strip()
            if heading_text:
                title = heading_text
                skip.add(heading)
                ctx.warnings.append("标题取自首个一级标题，已从正文剥离")
    if not title:
        title = Path(path).stem
        ctx.warnings.append("标题取自文件名")

    scope = _find_first(parser.root, "body") or parser.root
    blocks = _blocks(scope, ctx, skip=skip)
    body = "\n\n".join(block for block in blocks if block.strip())
    return title, body, ctx.warnings


__all__ = ["ImageSink", "convert_html"]

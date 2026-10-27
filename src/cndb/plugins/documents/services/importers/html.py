"""HTML → Markdown 转换：基于标准库 ``html.parser`` 构建轻量 DOM 后渲染.

支持的块级元素：h1-h6 / p / ul / ol / li / blockquote / pre / table / hr / div 容器；
行内元素：a / strong / b / em / i / del / code / br / img。
``<script>`` / ``<style>`` 等非正文内容丢弃；``<title>`` 或首个 ``<h1>`` 作为标题并从正文剥离。
图片：``data:`` URI 与批次内本地图片经 ``image_sink`` 落盘为站内附件，外链图片保留原 URL（决策 D2）。
内联 ``<svg>``（mermaid / ECharts 渲染结果）按原始标记落盘为 ``.svg`` 图片附件（ADR 0049 D13）。
"""

from __future__ import annotations

import base64
import binascii
import posixpath
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import override
from urllib.parse import unquote, urlsplit

from .errors import UnsupportedImport
from .normalize import collapse_whitespace, decode_text

#: 图片落盘回调：(字节, 建议文件名) → 站点文件 key；None 表示不落盘
ImageSink = Callable[[bytes, str], str | None]
#: 批次内本地图片：批次相对路径 → 原始字节
LocalImages = Mapping[str, bytes]

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
#: ``<svg>`` 原始标签名提取（``<svg`` / ``<foreignObject`` 等，保留大小写）
_TAG_NAME_RE = re.compile(r"<\s*([^\s/>]+)")
#: SVG 安全清洗（存入站内附件前剥离可执行内容；ADR 0049 D13）
_SVG_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_SVG_SCRIPT_SELF_RE = re.compile(r"<script\b[^>]*/>", re.IGNORECASE)
_SVG_EVENT_RE = re.compile(r"""\son[a-z]+\s*=\s*("[^"]*"|'[^']*')""", re.IGNORECASE)
_SVG_HREF_RE = re.compile(r"""(\s(?:xlink:)?href\s*=\s*)("[^"]*"|'[^']*')""", re.IGNORECASE)
_SVG_UNSAFE_URL_RE = re.compile(r"javascript:|data:text/html", re.IGNORECASE)
#: ``foreignObject`` 内的 HTML 空元素：HTML 序列化写 ``<br>``，作为独立 SVG 按 XML 解析会报错
_HTML_VOID_IN_SVG_RE = re.compile(
    r"<(br|hr|img|input|col|meta|link|area|base|embed|source|track|wbr)((?:\s[^>]*?[^/>])?)\s*>",
    re.IGNORECASE,
)
_XMLNS_ATTR = 'xmlns="http://www.w3.org/2000/svg"'
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
    """轻量 DOM 节点（``eq=False`` 保证可用对象身份做集合成员判断）.

    ``raw``：仅 ``<svg>`` 子树使用 —— 原始标记文本（保留大小写与命名空间，ADR 0049 D13）。
    """

    tag: str
    attrs: dict[str, str]
    children: list[_Node | str]
    raw: str = ""


def _xml_text(text: str) -> str:
    """按 XML 转义文本节点（``<style>`` CSS 里的 ``&`` / ``<`` 不转义会让 SVG 解析失败）."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _raw_tag_name(markup: str) -> str:
    """从原始标签文本取标签名（保留大小写：``foreignObject`` / ``clipPath`` 不能降成小写）."""
    matched = _TAG_NAME_RE.match(markup)
    return matched.group(1) if matched else ""


class _Builder(HTMLParser):
    """把 HTML 文本解析为 ``_Node`` 树（容忍未闭合与错序标签）.

    同时按下标捕获 ``<svg>`` 子树的**原始标记**存入 ``_Node.raw``：SVG 解析区分大小写
    （``viewBox`` / ``clipPath`` / ``foreignObject``），而 ``HTMLParser`` 会把标签名与属性
    名降为小写，重建会破坏渲染，故直接留存原文（ADR 0049 D13）。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, [])
        self._stack: list[_Node] = [self.root]
        self._svg_root: _Node | None = None
        self._svg_chunks: list[str] = []
        self._svg_tags: list[str] = []
        self._svg_depth = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        raw = self.get_starttag_text() or ""
        node = _Node(tag, {key.lower(): (value or "") for key, value in attrs}, [])
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)
        if tag == "svg" and self._svg_depth == 0:
            self._svg_root = node
        self._capture_open(tag, raw, self_closing=False)

    @override
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        raw = self.get_starttag_text() or ""
        node = _Node(tag, {key.lower(): (value or "") for key, value in attrs}, [])
        self._stack[-1].children.append(node)
        if tag == "svg" and self._svg_depth == 0:
            # 自闭合的 ``<svg .../>``：无子树，捕获后立即收尾
            self._svg_root = node
            self._svg_chunks = [raw]
            self._svg_tags = []
            self._finish_svg()
            return
        self._capture_open(tag, raw, self_closing=True)

    @override
    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._svg_depth:
            self._close_svg_tag(tag)
        if tag in _VOID_TAGS:
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    @override
    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)
        if self._svg_depth:
            self._svg_chunks.append(_xml_text(data))

    @override
    def handle_comment(self, data: str) -> None:
        # 注释默认被丢弃；SVG 子树里保留（部分渲染器把样式写在注释包裹的 ``<style>`` 外）
        if self._svg_depth:
            self._svg_chunks.append(f"<!--{data}-->")

    def _capture_open(self, tag: str, raw: str, *, self_closing: bool) -> None:
        """``<svg>`` 子树内的开始标签按原文累积（含命名空间与大小写）."""
        if self._svg_depth == 0 and tag != "svg":
            return
        if self._svg_depth == 0:
            self._svg_chunks = []
            self._svg_tags = []
        if tag == "svg":
            self._svg_depth += 1
        self._svg_chunks.append(raw)
        if not self_closing and tag not in _VOID_TAGS:
            self._svg_tags.append(_raw_tag_name(raw) or tag)

    def _close_svg_tag(self, tag: str) -> None:
        """结束标签：用原文大小写回填（``</foreignObject>`` 写错会让整份 SVG 解析失败）."""
        original = self._svg_tags.pop() if self._svg_tags else tag
        self._svg_chunks.append(f"</{original}>")
        if tag == "svg":
            self._svg_depth -= 1
            if self._svg_depth == 0:
                self._finish_svg()

    def _finish_svg(self) -> None:
        if self._svg_root is not None and self._svg_chunks:
            self._svg_root.raw = "".join(self._svg_chunks)
        self._svg_root = None
        self._svg_chunks = []
        self._svg_tags = []


@dataclass
class _Ctx:
    """渲染上下文：HTML 路径 + 本地图片索引 + 落盘回调 + 告警收集 + 图片计数.

    ``mhtml_resources``：MHTML 素材索引（``正文 src → (相对引用, 字节)``，ADR 0049），
    仅 MHTML 转换传入；命中时引用改写为 ``_assets/<名>`` 相对路径。
    ``base_url``：根 HTML 的原始地址（MHTML 取 ``Content-Location``），用于把指向自身的
    绝对链接改写为文内锚点（ADR 0049 D9）。
    """

    path: str = ""
    local_images: LocalImages | None = None
    sink: ImageSink | None = None
    warnings: list[str] = field(default_factory=list)
    images: int = 0
    mhtml_resources: Mapping[str, tuple[str, bytes]] | None = None
    base_url: str = ""
    anchors: dict[str, str] = field(default_factory=dict)
    _local_keys: dict[str, str] = field(default_factory=dict)


def _walk(node: _Node) -> Iterator[_Node]:
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _walk(child)


def _node_text(node: _Node) -> str:
    """节点纯文本：跳过脚本 / 样式 / 内联 SVG 等非正文子树（避免 CSS / JS 泄进正文）."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _SKIP_TAGS:
            parts.append(_node_text(child))
    return "".join(parts)


def _find_first(root: _Node, tag: str) -> _Node | None:
    for node in _walk(root):
        if node.tag == tag:
            return node
    return None


def _first_heading(root: _Node) -> _Node | None:
    for node in _walk(root):
        if node.tag in _HEADING_TAGS:
            return node
    return None


def _heading_anchor(text: str) -> str:
    """标题文本 → 预览区锚点 id（与前端 ``outline.headingAnchor`` 同算法）.

    小写 → 只保留 Unicode 字母数字 / 空白 / 连字符 → 空白折叠为连字符，前缀 ``doc-h-``。
    """
    kept = "".join(char for char in text.strip().lower() if char.isalnum() or char.isspace() or char == "-")
    return f"doc-h-{'-'.join(kept.split()) or 'empty'}"


def _anchor_index(root: _Node, skip: set[_Node]) -> dict[str, str]:
    """``id → 预览标题锚点``（ADR 0049 D9）：章节 / 标题自带 id 时改指向其所属标题.

    原文档的目录链接是 ``#s01``，但 Markdown 不保留元素 id；预览区标题 id 由标题文本生成，
    因此把已知 id 映射到同算法产出的 ``doc-h-…``，文内跳转才真正生效。被当作文档标题剥离
    的标题不入索引（否则锚点指向不存在的标题）。
    """
    anchors: dict[str, str] = {}
    latest: list[_Node | None] = [None]

    def visit(node: _Node) -> None:
        if node.tag in _HEADING_TAGS and node not in skip:
            latest[0] = node
        key = (node.attrs.get("id") or "").strip()
        if key and key not in anchors:
            heading = node if node.tag in _HEADING_TAGS else _first_heading(node)
            if heading is None or heading in skip:
                # 引注等无标题的锚点退化到所在位置之前最近的标题（点击可落到该节）
                heading = latest[0]
            text = collapse_whitespace(_node_text(heading)).strip() if heading is not None else ""
            if text:
                anchors[key] = _heading_anchor(text)
        for child in node.children:
            if isinstance(child, _Node):
                visit(child)

    visit(root)
    return anchors


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


def _is_external(src: str) -> bool:
    """外链图片：``//`` 开头或带 scheme（``http`` / ``https`` 等）."""
    if src.startswith("//"):
        return True
    try:
        return bool(urlsplit(src).scheme)
    except ValueError:  # pragma: no cover - 非法 URL（如坏 IPv6 字面量）
        return False


def _resolve_local_src(html_path: str, src: str) -> str | None:
    """HTML 相对图片 ``src`` → 批次内相对路径；绝对路径 / 越界路径返回 None."""
    try:
        raw = unquote(urlsplit(src).path).replace("\\", "/").strip()
    except ValueError:  # pragma: no cover - 与 _is_external 同一非法 URL 分支
        return None
    if not raw or raw.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(html_path), raw))
    if joined in {".", ".."} or joined.startswith("../"):
        return None
    return joined


def _sunk_image(ctx: _Ctx, data: bytes, name: str) -> str | None:
    """落盘一张图片并返回站内 key（``image_sink`` 缺失或拒绝时返回 None）."""
    if ctx.sink is not None:
        key = ctx.sink(data, name)
        if key:
            return key
    return None


def _local_image_markdown(ctx: _Ctx, src: str, alt: str) -> str:
    """批次内本地图片 → ``file:`` 引用；未随附 / 路径越界时降级占位并告警."""
    resolved = _resolve_local_src(ctx.path, src)
    if resolved is None:
        ctx.warnings.append(f"本地图片路径无效，已跳过：{src}")
        return f"_[图片未导入：{alt or src}]_"
    cached = ctx._local_keys.get(resolved)
    if cached:
        return f"![{alt or Path(resolved).name}](file:{cached})"
    data = (ctx.local_images or {}).get(resolved)
    if data is None:
        ctx.warnings.append(f"本地图片未随附，已跳过：{resolved}")
        return f"_[图片未导入：{alt or resolved}]_"
    ctx.images += 1
    name = Path(resolved).name or f"image{ctx.images}"
    key = _sunk_image(ctx, data, name)
    if key:
        ctx._local_keys[resolved] = key
        return f"![{alt or name}](file:{key})"
    ctx.warnings.append(f"内嵌图片未导入：{name}")
    return f"_[图片未导入：{name}]_"


def _mhtml_entry(resources: Mapping[str, tuple[str, bytes]], src: str) -> tuple[str, bytes] | None:
    """MHTML 素材查找唯一入口（ADR 0049 D3）：src 精确 → URL 解码 → 唯一 basename."""
    entry = resources.get(src)
    if entry is None:
        entry = resources.get(unquote(src))
    if entry is None:
        try:
            path = unquote(urlsplit(src).path)
        except ValueError:  # pragma: no cover - 与 _is_external 同一非法 URL 分支
            path = ""
        basename = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if basename:
            entry = resources.get(basename)
    return entry


def _mhtml_image_markdown(ctx: _Ctx, src: str, alt: str) -> str:
    """MHTML 素材命中：改写为 ``_assets/<名>`` 相对引用，sink 可用则落盘为 ``file:``（ADR 0049 D4）."""
    entry = _mhtml_entry(ctx.mhtml_resources or {}, src)
    if entry is None:
        if src.lower().startswith("cid:") or not _is_external(src):
            # 打包内应含而未匹配到的素材：占位 + 告警（外链除外，保留原 URL）
            ctx.warnings.append(f"MHTML 素材未包含，已跳过：{src}")
            return f"_[图片未导入：{alt or src}]_"
        return f"![{alt}]({src})"
    rel, payload = entry
    name = Path(rel).name
    ctx.images += 1
    key = _sunk_image(ctx, payload, name)
    if key:
        return f"![{alt or name}](file:{key})"
    return f"![{alt or name}]({rel})"


def _image_markdown(node: _Node, ctx: _Ctx) -> str:
    """``<img>`` → Markdown：data URI / 批次内本地图片落盘，外链保留原 URL."""
    src = (node.attrs.get("src") or "").strip()
    alt = (node.attrs.get("alt") or "").strip()
    if not src:
        return ""
    if src.lower().startswith("data:"):
        decoded = _decode_data_uri(src)
        if decoded is None:
            ctx.warnings.append("data URI 图片无法解析，已跳过")
            return f"_[图片未导入：{alt or 'image'}]_"
        ctx.images += 1
        name = f"image{ctx.images}{decoded[1]}"
        key = _sunk_image(ctx, decoded[0], name)
        if key:
            return f"![{alt or name}](file:{key})"
        ctx.warnings.append(f"内嵌图片未导入：{name}")
        return f"_[图片未导入：{name}]_"
    if ctx.mhtml_resources is not None:
        return _mhtml_image_markdown(ctx, src, alt)
    if _is_external(src) or ctx.local_images is None:
        return f"![{alt}]({src})"
    return _local_image_markdown(ctx, src, alt)


def _sanitize_svg(raw: str) -> str:
    """落盘前的 SVG 规范化与安全清洗（ADR 0049 D13）.

    规范化：``foreignObject`` 内的 HTML 空元素（``<br>`` 等）自闭合、根元素补齐 ``xmlns``，
    保证存为独立 ``.svg`` 后能按 XML 解析（``<img>`` 引入 SVG 走 XML 解析，``<br>`` 未闭合即整图失败）。
    清洗：剥 ``<script>`` / ``on*`` 事件 / 脚本 URL —— ``<img>`` 语义下本就不执行脚本，站内附件
    可被单独打开，故按纵深防御处理；``<style>`` 保留（配色 / 尺寸全靠它）。
    """
    out = _SVG_SCRIPT_RE.sub("", raw)
    out = _SVG_SCRIPT_SELF_RE.sub("", out)
    out = _SVG_EVENT_RE.sub("", out)
    out = _HTML_VOID_IN_SVG_RE.sub(lambda m: f"<{m.group(1)}{m.group(2)}/>", out)

    def _drop_unsafe(matched: re.Match[str]) -> str:
        # 脚本 URL 直接删掉整个属性，避免残留未声明的 ``xlink:`` 前缀（独立 SVG 按 XML 解析会报错）
        return "" if _SVG_UNSAFE_URL_RE.search(matched.group(2)) else matched.group(0)

    out = _SVG_HREF_RE.sub(_drop_unsafe, out)
    head, _, tail = out.partition(">")
    if "xmlns" not in head.lower():
        out = f"{head} {_XMLNS_ATTR}>{tail}" if tail else f"{head} {_XMLNS_ATTR}>"
    return out


def _svg_image_markdown(node: _Node, ctx: _Ctx) -> str:
    """内联 ``<svg>`` → ``.svg`` 图片附件（ADR 0049 D13）：矢量图表不再丢.

    ``sink`` 可用 → 落盘为 ``file:`` 引用（预览 / ``import_attachments=false`` 时回落占位，
    与 D8 同口径：不产生「图片未导入」告警）。原始标记损坏（未闭合等）时告警并跳过。
    """
    raw = (node.raw or "").strip()
    if not raw.lower().startswith("<svg") or "</svg" not in raw.lower():
        ctx.warnings.append("内联 SVG 图表无法解析，已跳过")
        return ""
    ctx.images += 1
    name = f"image{ctx.images}.svg"
    key = _sunk_image(ctx, _sanitize_svg(raw).encode("utf-8"), name)
    if key:
        return f"![图表](file:{key})"
    return f"_[图表未导入：{name}]_"


def _same_document_fragment(ctx: _Ctx, href: str) -> str | None:
    """指向「本文档自身」的链接 → 文内锚点；其余返回 None（ADR 0049 D9）.

    快照类 HTML / MHTML 的目录与引注链接多是 ``file:///.../同一文件.html#s01``，入库后该
    路径不存在；命中自身时优先映射到对应标题锚点（``#doc-h-…``），无对应标题则保留
    ``#fragment``。跨文档链接不动。
    """
    try:
        parts = urlsplit(href)
    except ValueError:  # pragma: no cover - 与 _is_external 同一非法 URL 分支
        return None
    if not parts.fragment:
        return None
    mapped = f"#{ctx.anchors.get(unquote(parts.fragment), parts.fragment)}"
    if not parts.scheme and not parts.netloc and not parts.path:
        # 纯 fragment（`#s01`）本就指向本文档
        return mapped
    if parts.scheme or parts.netloc:
        if not ctx.base_url:
            return None
        try:
            base = urlsplit(ctx.base_url)
        except ValueError:  # pragma: no cover - base_url 来自解析后的 Content-Location
            return None
        if (parts.scheme, parts.netloc, unquote(parts.path)) != (base.scheme, base.netloc, unquote(base.path)):
            return None
        return mapped
    name = unquote(parts.path).replace("\\", "/").rsplit("/", 1)[-1]
    if name and name == posixpath.basename(ctx.path.replace("\\", "/")):
        return mapped
    return None


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
        if not href:
            return stripped
        anchor = _same_document_fragment(ctx, href)
        return f"[{stripped}]({anchor or href})"
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
        text = collapse_whitespace("".join(parts)).strip()
        marker = f"{index}." if ordered else "-"
        lines.append("  " * indent + marker + (f" {text}" if text else ""))
        for sub in nested:
            lines.extend(_render_list(sub, ctx, ordered=sub.tag == "ol", indent=indent + 1))
    return lines


def _code_block(node: _Node) -> str:
    """``<pre>`` → 围栏代码块（语言取自 ``<code class="language-x">``）.

    内联 SVG（mermaid / ECharts 等渲染后图表）在 ``_node_text`` 中被跳过：``<pre>`` 只剩
    图表而无源码时返回空串，由 ``_blocks`` 另行把图表落为 ``.svg`` 图片（D13）。
    """
    code = _find_first(node, "code")
    source = code if code is not None else node
    raw = _node_text(source).strip("\n")
    if not raw.strip():
        return ""
    language = ""
    if code is not None:
        for token in (code.attrs.get("class") or "").split():
            if token.startswith("language-"):
                language = token[len("language-") :]
    return f"```{language}\n{raw}\n```"


def _cell_markdown(cell: _Node, ctx: _Ctx) -> str:
    text = collapse_whitespace("".join(_inline(child, ctx) for child in cell.children)).strip()
    return text.replace("|", "\\|")


def _span(node: _Node, name: str) -> int:
    """读取 ``rowspan`` / ``colspan``：非法值按 1，上限 1000（防御恶意超宽表）."""
    try:
        value = int(node.attrs.get(name) or "1")
    except ValueError:
        return 1
    return max(1, min(value, 1000))


def _table_markdown(node: _Node, ctx: _Ctx) -> str:
    """``<table>`` → Markdown 表格；``rowspan`` / ``colspan`` 展开为普通网格（D11）.

    Markdown 没有合并单元格：被 ``rowspan`` 覆盖的下方行重复该单元格文本，``colspan``
    多出的列留空，保证每一行的列数与表头一致、逐列语义不错位。
    """
    rows: list[list[tuple[str, int, int]]] = []
    for child in _walk(node):
        if child.tag != "tr":
            continue
        cells = [
            (_cell_markdown(cell, ctx), _span(cell, "rowspan"), _span(cell, "colspan"))
            for cell in child.children
            if isinstance(cell, _Node) and cell.tag in _CELL_TAGS
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    grid: dict[tuple[int, int], str] = {}
    width = 0
    for row_index, cells in enumerate(rows):
        column = 0
        for text, rowspan, colspan in cells:
            while (row_index, column) in grid:
                column += 1
            for offset in range(rowspan):
                for extra in range(colspan):
                    # 同一合并单元格的文字在每行首列重复，多列留空
                    grid[(row_index + offset, column + extra)] = text if extra == 0 else ""
            column += colspan
            width = max(width, column)
    if not width:
        return ""

    def line(row_index: int) -> list[str]:
        return [grid.get((row_index, column), "") for column in range(width)]

    lines = ["| " + " | ".join(line(0)) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(line(row_index)) + " |" for row_index in range(1, len(rows)))
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
        if child in skip:
            continue
        if child.tag == "svg":
            # 内联渲染的矢量图表（mermaid / ECharts）→ .svg 图片附件（D13）
            flush()
            image = _svg_image_markdown(child, ctx)
            if image:
                out.append(image)
            continue
        if child.tag in _SKIP_TAGS:
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
            lines = _render_list(child, ctx, ordered=tag == "ol")
            if lines:
                # 同一列表渲染为一个块：块间空行会让 Markdown 变成「松散列表」
                out.append("\n".join(lines))
        elif tag == "blockquote":
            flush()
            inner = _blocks(child, ctx, skip=skip)
            if inner:
                out.append("\n".join("> " + line if line else ">" for block in inner for line in block.split("\n")))
        elif tag == "pre":
            flush()
            # mermaid 等把渲染结果（内联 SVG）写进 <pre>：图表落为图片，剩余源码仍作代码块
            svg = _find_first(child, "svg")
            if svg is not None:
                image = _svg_image_markdown(svg, ctx)
                if image:
                    out.append(image)
            code = _code_block(child)
            if code:
                out.append(code)
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
        elif tag == "figure":
            flush()
            # 图题（figcaption）与图表（内联 SVG → 图片）都由递归输出（D13）
            out.extend(_blocks(child, ctx, skip=skip))
        elif tag in _BLOCK_CONTAINERS or tag in ("li", "td", "th", "tr"):
            flush()
            out.extend(_blocks(child, ctx, skip=skip))
        else:
            buffer.append(_inline(child, ctx))
    flush()
    return out


def convert_html(
    data: bytes,
    path: str,
    *,
    image_sink: ImageSink | None = None,
    local_images: LocalImages | None = None,
    mhtml_resources: Mapping[str, tuple[str, bytes]] | None = None,
    base_url: str = "",
) -> tuple[str, str, list[str]]:
    """把 ``.html`` / ``.htm`` 字节流转换为 ``(标题, 正文 Markdown, 告警)``.

    标题优先级：``<title>`` → 首个 ``<h1>``（并从正文剥离）→ 文件名。
    ``local_images`` 为同批上传图片（批次相对路径 → 字节），用于把 HTML 相对
    ``<img src>`` 内联为站内附件；不传时保持原相对 URL。
    ``mhtml_resources`` 为 MHTML 素材索引（ADR 0049），仅 MHTML 转换传入。
    ``base_url`` 为根 HTML 的原始地址（MHTML 取根 part 的 ``Content-Location``），用于
    把指向本文档的绝对链接改写为文内锚点；缺省时按文件名匹配退化处理。
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

    ctx = _Ctx(
        path=path,
        local_images=local_images,
        sink=image_sink,
        mhtml_resources=mhtml_resources,
        base_url=base_url,
    )
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
    ctx.anchors = _anchor_index(parser.root, skip)
    blocks = _blocks(scope, ctx, skip=skip)
    body = "\n\n".join(block for block in blocks if block.strip())
    return title, body, ctx.warnings


__all__ = ["ImageSink", "LocalImages", "convert_html"]

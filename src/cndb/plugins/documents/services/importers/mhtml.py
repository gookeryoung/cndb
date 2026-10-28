"""MHTML → Markdown 转换：标准库 ``email`` 解析 MIME multipart，根 HTML 复用 html 转换器（ADR 0049）.

- 根 HTML：首个 ``text/html`` part（``walk()`` 容忍嵌套 multipart），``decode_text`` 解码；
- 图片素材：``Content-Type: image/*`` 的 part，``get_payload(decode=True)`` 解 base64 / quoted-printable；
- 匹配顺序：``Content-Location`` 精确 → ``cid:<Content-ID>`` → 唯一 basename 兜底；未命中由
  html 转换器降级占位 + 告警；未打包进 MHTML 的外链保留原 URL（决策 D2/D3）；
- 非图片素材（CSS 等）丢弃（D6）；不保留 MHTML 原件（D7）；
- 指向根 HTML 自身的绝对链接（快照目录 / 引注的 ``file:///...#s01``）改写为文内锚点
  ``#s01``，跨文档链接原样保留（D9）。
"""

from __future__ import annotations

import base64
import posixpath
import re
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from .errors import UnsupportedImport
from .html import _MIME_SUFFIX, ImageSink, _mhtml_entry, convert_html
from .normalize import decode_text

#: 正文引用的合成相对路径前缀（import_attachments 关闭时素材落为该目录下的图片文档，D4）
ASSET_DIR = "_assets"

#: 素材文件名 stem 允许的最长长度
_MAX_STEM = 60

_IMG_SRC_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_UNSAFE_STEM_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


def _safe_stem(raw: str) -> str:
    """素材名 stem 清洗：保留中英文 / 数字 / ``._-``，其余折叠为 ``-``."""
    stem = _UNSAFE_STEM_RE.sub("-", raw).strip(".-")
    return stem[:_MAX_STEM] or "image"


def _dedupe_name(name: str, seen: set[str]) -> str:
    """重名素材递增：``img.png`` → ``img-2.png``（ADR 0049 边界 3）."""
    if name not in seen:
        seen.add(name)
        return name
    stem, dot, suffix = name.rpartition(".")
    index = 2
    while True:
        candidate = f"{stem}-{index}{dot}{suffix}" if dot else f"{name}-{index}"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
        index += 1


def _resource_name(location: str, ctype: str, seen: set[str]) -> str:
    """由 ``Content-Location`` 取安全文件名；无路径 / 无后缀时按 MIME 补后缀."""
    raw = unquote(urlsplit(location).path).replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = Path(raw).suffix.lower()
    if not suffix:
        suffix = _MIME_SUFFIX.get(ctype) or f".{ctype.split('/', 1)[1] or 'bin'}"
    return _dedupe_name(f"{_safe_stem(Path(raw).stem)}{suffix}", seen)


def _part_payload(part: Message) -> bytes | None:
    """传输编码解码后的字节；缺失 / 空返回 None."""
    payload = part.get_payload(decode=True)
    if not payload:
        return None
    return bytes(payload)


def _location_basename(location: str) -> str:
    return unquote(urlsplit(location).path).rsplit("/", 1)[-1].lower()


def _build_index(resources: list[tuple[str, str, str, bytes]]) -> dict[str, tuple[str, bytes]]:
    """构建「正文 src → (相对引用, 字节)」匹配索引（决策 D3）.

    每个素材注册多个键：``Content-Location`` 原串 / URL 解码串 / ``cid:<Content-ID>`` /
    唯一 basename（歧义 basename 不注册，避免张冠李戴）。
    """
    index: dict[str, tuple[str, bytes]] = {}
    basename_count: dict[str, int] = {}
    for _, location, _, _ in resources:
        basename = _location_basename(location)
        if basename:
            basename_count[basename] = basename_count.get(basename, 0) + 1
    for name, location, content_id, payload in resources:
        entry = (f"{ASSET_DIR}/{name}", payload)
        if location:
            index[location] = entry
            decoded = unquote(location)
            if decoded != location:
                index[decoded] = entry
            basename = _location_basename(location)
            if basename and basename_count.get(basename) == 1:
                index[basename] = entry
        if content_id:
            index[f"cid:{content_id}"] = entry
            index[f"cid:{content_id.strip('<>')}"] = entry
    return index


def _referenced_names(html_text: str, index: dict[str, tuple[str, bytes]]) -> set[str]:
    """扫描正文 ``<img src>`` 命中索引的素材名（与 html 转换器同一查找入口，D3）."""
    names: set[str] = set()
    for match in _IMG_SRC_RE.finditer(html_text):
        src = (match.group(1) or match.group(2) or "").strip()
        entry = _mhtml_entry(index, src)
        if entry is not None:
            names.add(posixpath.basename(entry[0]))
    return names


def parse_mhtml(data: bytes) -> tuple[str, str, list[tuple[str, str, str, bytes]]]:
    """解析 MHTML 字节流 → ``(根 HTML 文本, 根 HTML 的 Content-Location, 图片素材)``.

    图片素材为 ``[(素材名, Content-Location, Content-ID, 字节)]``；非 ``image/*`` part
    （CSS 等）直接丢弃；无 ``text/html`` part 或解析失败抛 ``UnsupportedImport``
    （调用方按「单条跳过」处理）。预览链路请用 :func:`parse_mhtml_full`。
    """
    html_text, html_location, resources, _stylesheets, _aux = parse_mhtml_full(data)
    return html_text, html_location, resources


def convert_mhtml(
    data: bytes, path: str, *, image_sink: ImageSink | None = None
) -> tuple[str, str, list[str], list[tuple[str, bytes]]]:
    """把 ``.mhtml`` / ``.mht`` 字节流转换为 ``(标题, 正文 Markdown, 告警, 素材清单)``.

    - 正文引用改写为 ``_assets/<素材名>`` 相对路径：``image_sink`` 返回 key 时落盘为
      ``file:`` 引用（开态），否则保留相对引用（关态 / 预览，D4/D8）；
    - 未被正文引用的图片素材在 ``image_sink`` 可用时直接落盘；
    - 素材清单为全部图片素材 ``(相对路径, 字节)``，供关态展开为批次条目。
    """
    html_text, html_location, resources = parse_mhtml(data)
    index = _build_index(resources)
    title, body, warnings = convert_html(
        html_text.encode("utf-8"),
        path,
        image_sink=image_sink,
        mhtml_resources=index,
        base_url=html_location,
    )
    referenced = _referenced_names(html_text, index)
    for name, _, _, payload in resources:
        if name in referenced or image_sink is None:
            continue
        image_sink(payload, name)
    assets = [(f"{ASSET_DIR}/{name}", payload) for name, _, _, payload in resources]
    return title, body, warnings, assets


__all__ = ["ASSET_DIR", "ImageSink", "build_preview_html", "convert_mhtml", "parse_mhtml", "parse_mhtml_full"]


def parse_mhtml_full(
    data: bytes,
) -> tuple[str, str, list[tuple[str, str, str, bytes]], list[tuple[str, str, str]], list[tuple[str, str, bytes]]]:
    """解析 MHTML → ``(根 HTML, 根 Content-Location, 图片素材, 样式表, 其他资源)``（需求 0064 C7/C8）.

    在 :func:`parse_mhtml` 基础上额外保留：

    - 样式表 ``[(location, content_id, css 文本)]``（``text/css`` part）；
    - 其他资源 ``[(location, content_type, 字节)]``（字体等非图片非 CSS part）。

    导入转换链路（:func:`parse_mhtml` / :func:`convert_mhtml`）仍按 D6 丢弃这些 part，
    仅预览链路使用。
    """
    try:
        message = BytesParser().parsebytes(data)
    except Exception as exc:
        raise UnsupportedImport("无法解析 MHTML 文件") from exc
    html_text = ""
    html_location = ""
    resources: list[tuple[str, str, str, bytes]] = []
    stylesheets: list[tuple[str, str, str]] = []
    aux: list[tuple[str, str, bytes]] = []
    seen: set[str] = set()
    for part in message.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and not html_text:
            payload = _part_payload(part)
            if payload is not None:
                html_text = decode_text(payload)
                html_location = (part.get("Content-Location") or "").strip()
            continue
        payload = _part_payload(part)
        if payload is None:
            continue
        location = (part.get("Content-Location") or "").strip()
        content_id = (part.get("Content-ID") or "").strip()
        if ctype.startswith("image/"):
            resources.append((_resource_name(location, ctype, seen), location, content_id, payload))
        elif ctype == "text/css":
            stylesheets.append((location, content_id, decode_text(payload)))
        else:
            aux.append((location, ctype, payload))
    if not html_text.strip():
        raise UnsupportedImport("MHTML 文件中没有 HTML 内容")
    return html_text, html_location, resources, stylesheets, aux


#: 预览用图片 MIME 嗅探：魔数 → MIME（需求 0064 C1）
_SNIFF_MIME: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
)


def _sniff_image_mime(payload: bytes) -> str:
    """按魔数嗅探图片 MIME；未命中回退 ``application/octet-stream``."""
    for magic, mime in _SNIFF_MIME:
        if payload.startswith(magic):
            return mime
    if payload.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    head = payload.lstrip()[:256].lower()
    if head.startswith((b"<svg", b"<?xml")):
        return "image/svg+xml"
    return "application/octet-stream"


def _data_uri(payload: bytes | str, mime: str | None = None) -> str:
    """``data:`` URI；mime 缺省时按魔数嗅探（字体等非图片 part 须显式传 Content-Type）."""
    raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    return f"data:{mime or _sniff_image_mime(raw)};base64,{base64.b64encode(raw).decode('ascii')}"


# ── 预览深度内联（需求 0064 C7-C9）──

#: 素材索引值类型：(字节或 CSS 文本, MIME 或 None)
_AssetEntry = tuple[bytes | str, str | None]

_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_TAG_ATTR_RE = re.compile(r"\b(rel|href)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE)
_SRCSET_ATTR_RE = re.compile(r"(\bsrcset\s*=\s*)(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
_CSS_URL_RE = re.compile(r"url\(\s*(?:'([^']*)'|\"([^\"]*)\"|([^)'\"]+?))\s*\)", re.IGNORECASE)


def _tag_attrs(tag: str) -> dict[str, str]:
    """从标签原文提取 rel / href 属性（首个出现为准，容忍无引号）."""
    attrs: dict[str, str] = {}
    for match in _TAG_ATTR_RE.finditer(tag):
        name = match.group(1).lower()
        value = match.group(2) or match.group(3) or match.group(4) or ""
        attrs.setdefault(name, value.strip())
    return attrs


def _resolve_url(url: str, base: str) -> str:
    """相对 URL 按所在资源的 Content-Location 解析；base 缺失原样返回."""
    url = url.strip()
    if not base:
        return url
    try:
        return urljoin(base, url)
    except ValueError:  # pragma: no cover - 非法 base 极罕见
        return url


def _lookup(index: dict[str, _AssetEntry], url: str, base: str) -> _AssetEntry | None:
    """素材三级匹配 + 相对解析兜底：复用 html 转换器唯一查找入口（需求 0064 C2/C8）."""
    return _mhtml_entry(index, url) or _mhtml_entry(index, _resolve_url(url, base))


def _rewrite_css_urls(css: str, index: dict[str, _AssetEntry], base: str) -> str:
    """CSS 文本中的 ``url(...)`` 命中素材索引时改写为 ``data:`` URI（需求 0064 C8）."""

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1) or match.group(2) or match.group(3) or ""
        entry = _lookup(index, raw, base)
        if entry is None:
            return match.group(0)
        payload, mime = entry
        return f"url({_data_uri(payload, mime)})"

    return _CSS_URL_RE.sub(repl, css)


def _register_keys(
    index: dict[str, _AssetEntry], location: str, content_id: str, value: _AssetEntry, basename_count: dict[str, int]
) -> None:
    """按「Content-Location 原串 / URL 解码 / cid / 唯一 basename」注册索引键（D3 同链路）."""
    if location:
        index[location] = value
        decoded = unquote(location)
        if decoded != location:
            index[decoded] = value
        basename = _location_basename(location)
        if basename and basename_count.get(basename) == 1:
            index[basename] = value
    if content_id:
        index[f"cid:{content_id}"] = value
        index[f"cid:{content_id.strip('<>')}"] = value


def _basename_counts(locations: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for location in locations:
        basename = _location_basename(location)
        if basename:
            counts[basename] = counts.get(basename, 0) + 1
    return counts


def build_preview_html(data: bytes) -> str:
    """MHTML 字节流 → 自包含预览 HTML（需求 0064 C1/C2/C7-C9）.

    - 根 HTML 原样保留（含内联 ``<style>``）；
    - 命中素材索引的 ``<img src>`` / ``srcset`` 候选内联为 ``data:`` URI；
    - 命中样式表索引的 ``<link rel="stylesheet">`` 原位替换为内联 ``<style>``；
    - 内联样式表与既有 ``<style>`` 块中的 ``url(...)``（背景图 / 字体等）同样内联；
    - 未命中引用保留原样；解析失败抛 ``UnsupportedImport``。

    产出的 HTML 仅在沙箱内渲染，脚本一律不执行。
    """
    html_text, html_location, resources, stylesheets, aux = parse_mhtml_full(data)

    # 资源索引：值统一为 (字节, MIME)——图片按魔数嗅探，字体等用 part 自带 Content-Type
    locations = [location for location, _, _, _ in resources]
    locations += [location for location, _, _ in stylesheets]
    locations += [location for location, _, _ in aux]
    basename_count = _basename_counts(locations)
    url_index: dict[str, _AssetEntry] = {}
    for _, location, content_id, payload in resources:
        _register_keys(url_index, location, content_id, (payload, None), basename_count)
    for location, content_id, css_text in stylesheets:
        _register_keys(url_index, location, content_id, (css_text.encode("utf-8"), "text/css"), basename_count)
    for location, ctype, payload in aux:
        _register_keys(url_index, location, "", (payload, ctype), basename_count)

    # 样式表索引：值统一为 (css 文本, 自身 Content-Location)——url() 需按其自身位置解析
    css_index: dict[str, _AssetEntry] = {}
    for location, content_id, css_text in stylesheets:
        _register_keys(css_index, location, content_id, (css_text, location), basename_count)

    def inline_link(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _tag_attrs(tag)
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "")
        if "stylesheet" not in rel or not href:
            return tag
        entry = _lookup(css_index, href, html_location)
        if entry is None:
            return tag
        css_text, css_base = entry
        # 样式表索引值恒为 (css 文本, Content-Location)，此处收窄文本类型
        assert isinstance(css_text, str)
        return f"<style>{_rewrite_css_urls(css_text, url_index, css_base or html_location)}</style>"

    def rewrite_srcset(match: re.Match[str]) -> str:
        value = match.group(2) or match.group(3) or ""

        def candidate(text: str) -> str:
            parts = text.split()
            entry = _lookup(url_index, parts[0], html_location)
            if entry is not None:
                parts[0] = _data_uri(entry[0], entry[1])
            return " ".join(parts)

        return f'{match.group(1)}"{", ".join(candidate(c.strip()) for c in value.split(",") if c.strip())}"'

    def rewrite_style_block(match: re.Match[str]) -> str:
        return match.group(1) + _rewrite_css_urls(match.group(2), url_index, html_location) + match.group(3)

    html = _LINK_TAG_RE.sub(inline_link, html_text)
    html = _STYLE_BLOCK_RE.sub(rewrite_style_block, html)
    html = _SRCSET_ATTR_RE.sub(rewrite_srcset, html)
    # <img src> 内联放最后：与 html 转换器同一查找入口，只替换 src 值本身
    out: list[str] = []
    pos = 0
    for match in _IMG_SRC_RE.finditer(html):
        src = (match.group(1) or match.group(2) or "").strip()
        entry = _lookup(url_index, src, html_location)
        if entry is None:
            continue
        start, end = match.span(1) if match.group(1) is not None else match.span(2)
        out.append(html[pos:start])
        out.append(_data_uri(entry[0], entry[1]))
        pos = end
    out.append(html[pos:])
    return "".join(out)

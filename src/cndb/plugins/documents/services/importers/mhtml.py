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
from urllib.parse import unquote, urlsplit

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


def parse_mhtml(data: bytes) -> tuple[str, str, list[tuple[str, str, str, bytes]]]:
    """解析 MHTML 字节流 → ``(根 HTML 文本, 根 HTML 的 Content-Location, 图片素材)``.

    图片素材为 ``[(素材名, Content-Location, Content-ID, 字节)]``；非 ``image/*`` part
    （CSS 等）直接丢弃；无 ``text/html`` part 或解析失败抛 ``UnsupportedImport``
    （调用方按「单条跳过」处理）。
    """
    try:
        message = BytesParser().parsebytes(data)
    except Exception as exc:
        raise UnsupportedImport("无法解析 MHTML 文件") from exc
    html_text = ""
    html_location = ""
    resources: list[tuple[str, str, str, bytes]] = []
    seen: set[str] = set()
    for part in message.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and not html_text:
            payload = _part_payload(part)
            if payload is not None:
                html_text = decode_text(payload)
                html_location = (part.get("Content-Location") or "").strip()
            continue
        if ctype.startswith("image/"):
            payload = _part_payload(part)
            if payload is None:
                continue
            location = (part.get("Content-Location") or "").strip()
            content_id = (part.get("Content-ID") or "").strip()
            resources.append((_resource_name(location, ctype, seen), location, content_id, payload))
    if not html_text.strip():
        raise UnsupportedImport("MHTML 文件中没有 HTML 内容")
    return html_text, html_location, resources


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


__all__ = ["ASSET_DIR", "ImageSink", "build_preview_html", "convert_mhtml", "parse_mhtml"]


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


def _data_uri(payload: bytes) -> str:
    return f"data:{_sniff_image_mime(payload)};base64,{base64.b64encode(payload).decode('ascii')}"


def build_preview_html(data: bytes) -> str:
    """MHTML 字节流 → 自包含预览 HTML（需求 0064 C1/C2）.

    根 HTML 原样保留（含内联 ``<style>``，D6 口径不变），仅把命中素材索引的
    ``<img src>`` 内联为 ``data:`` URI；未命中引用保留原样。解析失败抛
    ``UnsupportedImport``。产出的 HTML 仅在沙箱内渲染，脚本一律不执行。
    """
    html_text, _location, resources = parse_mhtml(data)
    index = _build_index(resources)
    out: list[str] = []
    pos = 0
    for match in _IMG_SRC_RE.finditer(html_text):
        src = (match.group(1) or match.group(2) or "").strip()
        entry = _mhtml_entry(index, src)
        if entry is None:
            continue
        start, end = match.span(1) if match.group(1) is not None else match.span(2)
        out.append(html_text[pos:start])
        out.append(_data_uri(entry[1]))
        pos = end
    out.append(html_text[pos:])
    return "".join(out)

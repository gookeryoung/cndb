"""正文内嵌图表块（ADR 0052）：```chart 围栏 + JSON 定义的解析 / 序列化 / 渲染.

图表定义随正文分发，正文自包含：``template`` + ``config`` + ``width`` + ``title``
即足以渲染，不再按 ``documents_chart`` ID 查库。本模块是后端唯一判定入口：

- 块必须**独占段落**（与 ``{{table:…}}`` / 旧图表引用的段落级口径一致）；
- JSON 规范序列化（键排序）→ SHA-256 前 12 位 = 内容指纹（导出资产命名 / 导入去重）；
- 渲染复用唯一渲染器 :func:`charts.render_chart`，坏块降级为占位（I5，不阻断整篇）；
- 单块 ≤ 32KB、单篇 ≤ 50 块（D2），超限在编辑 / 导入侧拒绝或告警。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.documents.services import charts
from cndb.plugins.documents.services.export.ref_width import DEFAULT_REF_WIDTH, parse_ref_width

#: 围栏语言标识（`` ```chart ``）
INLINE_CHART_LANG = "chart"
#: 块格式版本：只接受 1，未知版本降级
INLINE_CHART_VERSION = 1
#: 单块定义上限（序列化前正文片段字节数）
MAX_BLOCK_BYTES = 32 * 1024
#: 单篇正文图表块上限
MAX_BLOCKS_PER_DOC = 50

#: 错误码（前端 / 导出 / 导入告警共用，文案见 :func:`block_error_message`）
ERROR_JSON_INVALID = "json_invalid"
ERROR_VERSION_UNSUPPORTED = "version_unsupported"
ERROR_TEMPLATE_MISSING = "template_missing"
ERROR_CONFIG_INVALID = "config_invalid"
ERROR_TOO_LARGE = "too_large"

#: 起始围栏：0–3 空格缩进 + 3 个以上反引号 + ``chart``（可带尾随空白）
_FENCE_START_RE = re.compile(r"^[ \t]{0,3}(`{3,})chart[ \t]*$")
#: 结束围栏：与起始同长度或更长的反引号（可带尾随空白）
_FENCE_END_RE = re.compile(r"^[ \t]{0,3}(`{3,})[ \t]*$")
#: 段落分隔（与前端 splitRefs / 旧 chart_refs 同构）
_PARAGRAPH_SPLIT_RE = re.compile(r"(\n\n+)")

_ERROR_TEXT: dict[str, str] = {
    ERROR_JSON_INVALID: "JSON 格式错误",
    ERROR_VERSION_UNSUPPORTED: "版本不受支持",
    ERROR_TEMPLATE_MISSING: "模板不存在或已下线",
    ERROR_CONFIG_INVALID: "配置校验失败",
    ERROR_TOO_LARGE: "定义超过 32KB",
}


@dataclass(frozen=True)
class InlineChartBlock:
    """正文中的一个图表块；``error`` 非空时其余渲染字段不可信.

    ``source`` 是块原文（含围栏），导出 Markdown 时原样保留；``legacy_id`` 仅由
    存量迁移写入，不参与指纹、不参与渲染。
    """

    source: str
    template_key: str = ""
    title: str = ""
    width: int = DEFAULT_REF_WIDTH
    config: dict[str, Any] = field(default_factory=dict)
    version: int = INLINE_CHART_VERSION
    legacy_id: int | None = None
    fingerprint: str = ""
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def block_error_message(code: str) -> str:
    """错误码 → 中文占位文案（预览 / 导出 / 导入告警统一口径）."""
    return f"[图表定义无效：{_ERROR_TEXT.get(code, code)}]"


def _canonical_payload(
    *,
    template_key: str,
    config: Any,
    width: int,
    title: str,
    version: int,
) -> dict[str, Any]:
    """指纹输入：不含 ``legacy_id``，键序固定（JSON 键排序后编码）."""
    return {
        "version": version,
        "template": template_key,
        "title": title,
        "width": width,
        "config": config if isinstance(config, dict) else {},
    }


def _resolve_width(value: object) -> int:
    """宽度归一：接受 int / 字符串 / None，非法越界回退默认."""
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return DEFAULT_REF_WIDTH
    return parse_ref_width(value)


def chart_fingerprint(template_key: str, config: Any, width: int, title: str = "") -> str:
    """内容指纹：规范 JSON 的 SHA-256 前 12 位（导出资产命名 / 导入去重）."""
    raw = json.dumps(
        _canonical_payload(
            template_key=template_key,
            config=config,
            width=width,
            title=title,
            version=INLINE_CHART_VERSION,
        ),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def serialize_inline_chart_block(
    *,
    template_key: str,
    config: Any,
    width: int | None = None,
    title: str = "",
    legacy_id: int | None = None,
    version: int = INLINE_CHART_VERSION,
    extra: dict[str, Any] | None = None,
) -> str:
    """生成可读的内嵌块（2 空格缩进、键顺序固定）；编辑器 / 迁移共用."""
    pct = _resolve_width(width)
    payload: dict[str, Any] = {
        "version": version,
        "template": template_key,
        "title": title,
        "width": pct,
        "config": config if isinstance(config, dict) else {},
    }
    if legacy_id is not None:
        payload["legacy_id"] = int(legacy_id)
    for key, value in (extra or {}).items():
        if key not in payload:
            payload[key] = value
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    return f"```{INLINE_CHART_LANG}\n{body}\n```"


def _parse_paragraph(paragraph: str) -> InlineChartBlock | None:
    """把独占段落解析为图表块；不是围栏块（含未闭合围栏）返回 None."""
    text = paragraph.strip("\n")
    if not text:
        return None
    lines = text.split("\n")
    start = _FENCE_START_RE.match(lines[0])
    if start is None:
        return None
    ticks = len(start.group(1))
    end = _FENCE_END_RE.match(lines[-1]) if len(lines) > 1 else None
    if end is None or len(end.group(1)) < ticks:
        return None

    source = "\n".join(lines)
    if len(source.encode("utf-8")) > MAX_BLOCK_BYTES:
        return InlineChartBlock(source=source, error=ERROR_TOO_LARGE)

    body = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(body) if body else None
    except (json.JSONDecodeError, ValueError):
        return InlineChartBlock(source=source, error=ERROR_JSON_INVALID)
    if not isinstance(payload, dict):
        return InlineChartBlock(source=source, error=ERROR_JSON_INVALID)

    version = payload.get("version", INLINE_CHART_VERSION)
    if not isinstance(version, int) or version != INLINE_CHART_VERSION:
        return InlineChartBlock(source=source, error=ERROR_VERSION_UNSUPPORTED)

    template_key = payload.get("template")
    if not isinstance(template_key, str) or not template_key.strip():
        return InlineChartBlock(source=source, error=ERROR_TEMPLATE_MISSING)
    template_key = template_key.strip()
    if charts.get_template(template_key) is None:
        return InlineChartBlock(source=source, error=ERROR_TEMPLATE_MISSING)

    config = payload.get("config")
    if not isinstance(config, dict):
        return InlineChartBlock(source=source, error=ERROR_CONFIG_INVALID)

    raw_title = payload.get("title") if isinstance(payload.get("title"), str) else ""
    raw_width = payload.get("width")
    legacy_id = payload.get("legacy_id")
    extra = {
        key: value
        for key, value in payload.items()
        if key not in {"version", "template", "title", "width", "config", "legacy_id"}
    }
    width = _resolve_width(raw_width)
    return InlineChartBlock(
        source=source,
        template_key=template_key,
        title=raw_title.strip(),
        width=width,
        config=config,
        version=version,
        legacy_id=legacy_id if isinstance(legacy_id, int) else None,
        fingerprint=chart_fingerprint(template_key, config, width, raw_title.strip()),
        extra=extra,
    )


def parse_inline_chart_block(paragraph: str) -> InlineChartBlock | None:
    """解析一个独占段落的图表块；非图表块返回 None，坏块带 ``error``."""
    return _parse_paragraph(paragraph)


def split_inline_chart_segments(content: str) -> list[str | InlineChartBlock]:
    """按段落切分正文：``str`` 为原样 Markdown，``InlineChartBlock`` 为图表块.

    段落分隔符保留在相邻 Markdown 片段内（导出 / 预览无需额外处理空行）。
    """
    if not content:
        return []
    parts = _PARAGRAPH_SPLIT_RE.split(content)
    segments: list[str | InlineChartBlock] = []
    buf: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            buf.append(part)
            continue
        block = _parse_paragraph(part) if part else None
        if block is None:
            buf.append(part)
            continue
        if buf:
            segments.append("".join(buf))
            buf = []
        segments.append(block)
    if buf:
        segments.append("".join(buf))
    return segments


def iter_inline_chart_blocks(content: str) -> Iterator[InlineChartBlock]:
    """按出现顺序迭代正文中的图表块（含坏块）."""
    for segment in split_inline_chart_segments(content):
        if isinstance(segment, InlineChartBlock):
            yield segment


def validate_document_blocks(content: str) -> list[str]:
    """导入 / 保存侧校验：返回告警文案（空 = 通过）.

    坏块保留原文、不阻断整篇；数量超限给出告警（不截断既有内容）。
    """
    warnings: list[str] = []
    blocks = list(iter_inline_chart_blocks(content))
    if len(blocks) > MAX_BLOCKS_PER_DOC:
        warnings.append(f"图表块数量 {len(blocks)} 超过单篇上限 {MAX_BLOCKS_PER_DOC}")
    for block in blocks:
        if block.error:
            warnings.append(block_error_message(block.error))
    return warnings


def render_inline_chart(block: InlineChartBlock) -> charts.ChartDocument:
    """唯一渲染入口：坏块 / 模板下线降级为占位整幅图（I5）."""
    if block.error:
        return charts.render_degraded(block.legacy_id or 0, block_error_message(block.error))
    try:
        return charts.render_chart(block.template_key, block.config)
    except charts.BadRequestTemplateError:
        return charts.render_degraded(block.legacy_id or 0, block_error_message(ERROR_TEMPLATE_MISSING))


def render_inline_chart_svg(block: InlineChartBlock) -> str:
    """块渲染为 SVG 文本（成员 / 游客渲染端点共用）."""
    return charts.to_svg(render_inline_chart(block))


#: Markdown 导出侧单块渲染器：入参块，返回 ``(SVG 字节, alt 文本)``
MarkdownBlockRenderer = Callable[[InlineChartBlock], tuple[bytes, str]]


def _markdown_alt(block: InlineChartBlock) -> str:
    """图片 alt：标题（去方括号），无标题回退「图表」."""
    alt = (block.title or "").replace("[", "").replace("]", "").strip()
    return alt or "图表"


def rewrite_markdown_chart_blocks(content: str) -> tuple[str, dict[str, bytes]]:
    """Markdown 导出：保留定义块并追加 ``![标题](assets/chart-<指纹>.svg)``.

    - 坏块 / 模板下线块**原样保留**（可在本平台重导入后修复，D11）；
    - 相同指纹只产一份资产；资产名不绑定实例 ID（D6）。
    """
    assets: dict[str, bytes] = {}
    segments = split_inline_chart_segments(content)
    if not segments:
        return content, assets

    out: list[str] = []
    for segment in segments:
        if isinstance(segment, str):
            out.append(segment)
            continue
        out.append(segment.source)
        if segment.error or not segment.fingerprint:
            continue
        rel = f"assets/chart-{segment.fingerprint}.svg"
        if rel not in assets:
            assets[rel] = charts.to_svg(render_inline_chart(segment)).encode("utf-8")
        out.append(f"\n\n![{_markdown_alt(segment)}]({rel})")
    return "".join(out), assets


def migrate_legacy_chart_refs(
    content: str,
    resolve: Callable[[int, int], tuple[int, str, str, dict[str, Any]] | None],
) -> tuple[str, int]:
    """旧 ``{{chart:<id>|width=N}}`` → 内嵌块（迁移 / 旧备份兼容用）.

    ``resolve(chart_id, width)`` 返回 ``(workspace_id, title, template_key, config)``
    或 None（实例不存在 / 跨工作区）→ 写入与今日一致的降级文字。
    返回 ``(新正文, 改动处数)``；无旧引用时原样返回。
    """
    legacy_re = re.compile(r"^\{\{chart:(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$")
    param_re = re.compile(r"\|([a-zA-Z]+)=([^|}]+)")
    if not content or "{{chart:" not in content:
        return content, 0

    parts = _PARAGRAPH_SPLIT_RE.split(content)
    changed = 0
    for index, part in enumerate(parts):
        if index % 2 == 1 or not part:
            continue
        match = legacy_re.match(part.strip())
        if match is None:
            continue
        chart_id = int(match.group(1))
        width = DEFAULT_REF_WIDTH
        for key, value in param_re.findall(match.group(2) or ""):
            if key == "width":
                width = parse_ref_width(value)
        resolved = resolve(chart_id, width)
        if resolved is None:
            parts[index] = f"[图表引用无效：图表 #{chart_id} 不存在或无访问权限]"
        else:
            _ws, title, template_key, config = resolved
            parts[index] = serialize_inline_chart_block(
                template_key=template_key,
                config=config,
                width=width,
                title=title,
                legacy_id=chart_id,
            )
        changed += 1
    return "".join(parts), changed


__all__ = [
    "ERROR_CONFIG_INVALID",
    "ERROR_JSON_INVALID",
    "ERROR_TEMPLATE_MISSING",
    "ERROR_TOO_LARGE",
    "ERROR_VERSION_UNSUPPORTED",
    "INLINE_CHART_LANG",
    "INLINE_CHART_VERSION",
    "MAX_BLOCKS_PER_DOC",
    "MAX_BLOCK_BYTES",
    "InlineChartBlock",
    "block_error_message",
    "chart_fingerprint",
    "iter_inline_chart_blocks",
    "migrate_legacy_chart_refs",
    "parse_inline_chart_block",
    "render_inline_chart",
    "render_inline_chart_svg",
    "rewrite_markdown_chart_blocks",
    "serialize_inline_chart_block",
    "split_inline_chart_segments",
    "validate_document_blocks",
]

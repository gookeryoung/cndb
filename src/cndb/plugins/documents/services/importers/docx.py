"""docx → Markdown 转换：标题层级 / 段落 / 列表 / 表格 / 内嵌图片.

返回 ``(title, body, warnings)``；内嵌图片经 ``image_sink`` 落盘为站内附件
（``![别名](file:<key>)``，对应决策 D2），sink 缺失或返回 None 时降级为占位文本。
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from docx import Document as _DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .errors import UnsupportedImport

#: 图片落盘回调：(字节, 建议文件名) → 站点文件 key；None 表示不落盘
ImageSink = Callable[[bytes, str], str | None]

_HEADING_NAME_RE = re.compile(r"^Heading\s*(\d+)$")
_HEADING_ID_RE = re.compile(r"^Heading(\d+)$")
_BULLET_STYLE_RE = re.compile(r"^List Bullet(\s+(\d))?$")
_NUMBER_STYLE_RE = re.compile(r"^List Number(\s+(\d))?$")
_STRIP_TITLE_CHARS = "*`~_\u200b"


def _iter_blocks(document: Any) -> Iterator[Paragraph | Table]:
    """按文档流顺序产出段落与表格（保持原始顺序）."""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _iter_run_images(run: Any, part: Any) -> Iterator[tuple[bytes, str]]:
    """产出 run 内嵌的图片字节与建议后缀（best-effort，缺失静默跳过）."""
    for blip in run._element.findall(".//" + qn("a:blip")):
        rid = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if not rid:
            continue
        related = getattr(part, "related_parts", {}).get(rid)
        if related is None:
            continue
        blob = getattr(related, "blob", None)
        if not blob:
            continue
        suffix = Path(str(getattr(related, "partname", ""))).suffix.lower() or ".png"
        yield blob, suffix


def _image_markdown(
    sink: ImageSink | None,
    blob: bytes,
    suffix: str,
    name: str,
    warnings: list[str],
) -> str:
    """图片 → Markdown：有 sink 则落盘引用，否则占位并记告警."""
    filename = f"{name}{suffix}"
    if sink is not None:
        key = sink(blob, filename)
        if key:
            return f"![{filename}](file:{key})"
    warnings.append(f"内嵌图片未导入：{filename}")
    return f"_[图片未导入：{filename}]_"


def _run_markdown(run: Any, document: Any, sink: ImageSink | None, warnings: list[str], counter: dict[str, int]) -> str:
    """单个 run → Markdown 片段（图片 + 加粗/斜体文本）."""
    parts: list[str] = []
    for blob, suffix in _iter_run_images(run, document.part):
        counter["images"] += 1
        parts.append(_image_markdown(sink, blob, suffix, f"image{counter['images']}", warnings))
    text = run.text or ""
    if text:
        if run.bold and run.italic:
            text = f"***{text}***"
        elif run.bold:
            text = f"**{text}**"
        elif run.italic:
            text = f"*{text}*"
        parts.append(text)
    return "".join(parts)


def _paragraph_markdown(
    paragraph: Any, document: Any, sink: ImageSink | None, warnings: list[str], counter: dict[str, int]
) -> str:
    """段落 → Markdown 文本（逐 run 拼接，保留图片与格式）."""
    text = "".join(_run_markdown(run, document, sink, warnings, counter) for run in paragraph.runs).strip()
    if not text:
        # 超链接等 run 不在 paragraph.runs 中时的兜底
        fallback = (paragraph.text or "").strip()
        if fallback:
            return fallback
    return text


def _heading_level(paragraph: Any) -> int:
    """识别标题层级：段落样式名 / style_id 命中 ``Heading n`` / ``Title``."""
    style = paragraph.style
    if style is None:
        return 0
    name = (style.name or "").strip()
    if name.lower() == "title":
        return 1
    match = _HEADING_NAME_RE.match(name) or _HEADING_ID_RE.match((style.style_id or "").strip())
    if match is None:
        return 0
    return max(1, min(6, int(match.group(1))))


def _list_marker(paragraph: Any) -> str:
    """列表项标记：无序为 ``- ``，有序为 ``1. ``（不追踪编号，渲染端自动排序）."""
    name = (paragraph.style.name or "").strip() if paragraph.style is not None else ""
    if _BULLET_STYLE_RE.match(name):
        return "- "
    if _NUMBER_STYLE_RE.match(name):
        return "1. "
    return ""


def _cell_text(cell: Any) -> str:
    text = " ".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _table_markdown(table: Any) -> str:
    """表格 → pipe table（首行为表头，缺格补空）."""
    rows = [[_cell_text(cell) for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    lines = ["| " + " | ".join(rows[0] + [""] * (width - len(rows[0]))) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row + [""] * (width - len(row))) + " |")
    return "\n".join(lines)


def convert_docx(data: bytes, path: str, *, image_sink: ImageSink | None = None) -> tuple[str, str, list[str]]:
    """把 ``.docx`` 字节流转换为 ``(标题, 正文 Markdown, 告警)``.

    标题优先级：core properties ``title`` → 首个一级标题（并从正文剥离）→ 文件名。
    文件损坏 / 非法时抛 ``UnsupportedImport``。
    """
    warnings: list[str] = []
    try:
        document = _DocxDocument(io.BytesIO(data))
    except Exception as exc:  # 交由调用方按「单条跳过」处理
        raise UnsupportedImport("无法解析 docx：文件已损坏或不是有效的 Word 文档") from exc

    counter = {"images": 0}
    blocks: list[str] = []
    first_heading_index: int | None = None
    first_heading_text = ""

    for block in _iter_blocks(document):
        if isinstance(block, Table):
            markdown = _table_markdown(block)
            if markdown:
                blocks.append(markdown)
            continue
        text = _paragraph_markdown(block, document, image_sink, warnings, counter)
        if not text:
            continue
        level = _heading_level(block)
        marker = _list_marker(block)
        if level:
            if first_heading_index is None and level == 1:
                first_heading_index = len(blocks)
                first_heading_text = text.strip().strip(_STRIP_TITLE_CHARS).strip()
            blocks.append("#" * level + " " + text)
        elif marker:
            blocks.append(marker + text)
        else:
            blocks.append(text)

    title = ""
    properties = getattr(document, "core_properties", None)
    if properties is not None:
        title = (getattr(properties, "title", "") or "").strip()
    if not title and first_heading_index is not None:
        title = first_heading_text
        del blocks[first_heading_index]
        warnings.append("标题取自首个一级标题，已从正文剥离")
    if not title:
        title = Path(path).stem
        warnings.append("标题取自文件名")

    return title, "\n\n".join(blocks), warnings


__all__ = ["ImageSink", "convert_docx"]

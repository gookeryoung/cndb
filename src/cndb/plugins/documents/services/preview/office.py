"""Office 原件在线预览（ADR 0087）：xlsx / docx → 自包含 HTML.

设计口径：

- **唯一入口**：``build_office_preview`` 按 ``content_type`` 分派，路由只调它；
- **自包含**：内联 CSS，图片一律 ``data:`` URI，无外部资源引用；
- **只读生成**：输出全为后端模板拼接，所有来源文本 ``html.escape``，脚本不可能执行；
- **有界**：工作表数 / 行列数 / 单元格数 / 图片数 / 输出体积都有硬上限，超限截断提示；
- **复用**：块遍历与 run 图片抽取复用导入侧 ``importers.docx`` 的实现，图片 MIME 嗅探复用
  ``importers.mhtml`` 的魔数判定，避免两套解析逻辑漂移。

解析失败（损坏 / 加密 / 旧版二进制格式）统一抛 :class:`UnsupportedPreview`，由路由转 400。
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import io
import re
from typing import Any

from cndb.plugins.documents.models import CONTENT_TYPE_WORD, CONTENT_TYPE_XLSX
from cndb.plugins.documents.services.importers.docx import _iter_blocks, _iter_run_images
from cndb.plugins.documents.services.importers.mhtml import _sniff_image_mime


class UnsupportedPreview(Exception):
    """原件无法渲染为预览 HTML（损坏 / 加密 / 旧版二进制格式）."""


# ── 有界上限（ADR 0087 C4）──

#: 单个工作簿最多渲染的工作表数
MAX_SHEETS = 20
#: 单个工作表最多渲染的行数 / 列数
MAX_SHEET_ROWS = 2000
MAX_SHEET_COLS = 100
#: 全工作簿最多渲染的单元格数（跨表累计，防止「很多中等表」叠加）
MAX_TOTAL_CELLS = 50_000
#: 单元格文本最大长度（超出截断）
MAX_CELL_CHARS = 2000
#: 预览最多内联的图片张数与总字节
MAX_IMAGES = 200
MAX_IMAGE_BYTES = 16 * 1024 * 1024
#: 输出 HTML 体积上限（字符数）
MAX_HTML_CHARS = 4 * 1024 * 1024

#: 旧版二进制 Office MIME（解析库不支持，保持下载查看）
LEGACY_MIMES: frozenset[str] = frozenset({"application/vnd.ms-excel", "application/msword"})

_PAGE_STYLE = """
:root { color-scheme: light dark; }
body { margin: 0; padding: 20px 24px 40px; font: 14px/1.7 -apple-system, "Segoe UI", "Noto Sans SC", sans-serif;
  color: #1f2937; background: #fff; }
h1 { font-size: 22px; margin: 0 0 16px; }
h2 { font-size: 18px; margin: 24px 0 10px; }
h3 { font-size: 16px; margin: 20px 0 8px; }
p { margin: 0 0 10px; }
ul, ol { margin: 0 0 10px; padding-left: 24px; }
table { border-collapse: collapse; margin: 0 0 16px; font-size: 13px; max-width: 100%; }
table.sheet { display: block; overflow: auto; max-height: 70vh; }
th, td { border: 1px solid #d7dee8; padding: 4px 8px; text-align: left; vertical-align: top; white-space: pre-wrap; }
th { background: #f1f5f9; font-weight: 600; position: sticky; top: 0; }
img { max-width: 100%; height: auto; }
.cn-preview-title { font-size: 12px; color: #64748b; margin: 0 0 12px; }
.cn-preview-empty, .cn-preview-note { color: #64748b; font-size: 12px; }
@media (prefers-color-scheme: dark) {
  body { background: #0f172a; color: #e2e8f0; }
  th { background: #1e293b; }
  th, td { border-color: #334155; }
  .cn-preview-title, .cn-preview-empty, .cn-preview-note { color: #94a3b8; }
}
"""

_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*(\d)$", re.IGNORECASE)


def _page(body: str, *, kind: str) -> str:
    """套上自包含页面骨架（标题仅为格式提示，不含原件正文）."""
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(kind)}预览</title><style>{_PAGE_STYLE}</style></head>"
        f'<body><p class="cn-preview-title">{html.escape(kind)}原件预览（只读）</p>{body}</body></html>'
    )


def _note(text: str) -> str:
    return f'<p class="cn-preview-note">{html.escape(text)}</p>'


def _truncated_note() -> str:
    return _note("内容超出预览上限，已截断；完整内容请下载原件查看。")


# ── 表格（xlsx）──


def _cell_text(value: Any) -> str:
    """单元格值 → 展示文本：日期 / 数值 / 布尔按可读形式，文本原样."""
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        # Excel 只有「日期」单元格时 openpyxl 返回零点的 datetime，按日期展示更贴近原件
        if value.time() == dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dt.time):
        return value.isoformat()
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.15g}"
    return str(value)[:MAX_CELL_CHARS]


def _sheet_html(ws: Any, budget: list[int], state: list[bool]) -> str:
    """渲染一个工作表为 ``<section>``；``budget`` 为跨表单元格余量，``state`` 为截断标记."""
    rows: list[list[str]] = []
    columns = 0
    for row in ws.iter_rows(max_row=MAX_SHEET_ROWS, max_col=MAX_SHEET_COLS, values_only=True):
        if budget[0] <= 0 or len(rows) >= MAX_SHEET_ROWS:
            state[0] = True
            break
        cells = [_cell_text(value) for value in row]
        while cells and cells[-1] == "":
            cells.pop()
        if not cells:
            continue
        budget[0] -= len(cells)
        columns = max(columns, len(cells))
        rows.append(cells)

    title = f"<h2>{html.escape(str(ws.title or '工作表'))}</h2>"
    if not rows:
        return f'<section>{title}<p class="cn-preview-empty">（空白工作表）</p></section>'

    header, *body = rows

    def cells_html(cells: list[str], tag: str) -> str:
        padded = cells + [""] * (columns - len(cells))
        return "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in padded)

    head = f"<thead><tr>{cells_html(header, 'th')}</tr></thead>"
    body_rows = "".join(f"<tr>{cells_html(cells, 'td')}</tr>" for cells in body)
    return f'<section>{title}<table class="sheet">{head}<tbody>{body_rows}</tbody></table></section>'


def build_spreadsheet_html(data: bytes) -> str:
    """xlsx 原件 → 多工作表表格 HTML（ADR 0087 C1）."""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise UnsupportedPreview(f"Excel 原件无法解析：{exc}") from exc

    parts: list[str] = []
    budget = [MAX_TOTAL_CELLS]
    state = [False]
    size = 0
    try:
        sheets = list(workbook.worksheets)
        for ws in sheets[:MAX_SHEETS]:
            markup = _sheet_html(ws, budget, state)
            parts.append(markup)
            size += len(markup)
            if state[0] or size > MAX_HTML_CHARS:
                state[0] = True
                break
        if len(sheets) > MAX_SHEETS:
            state[0] = True
    except UnsupportedPreview:
        raise
    except Exception as exc:
        raise UnsupportedPreview(f"Excel 原件无法解析：{exc}") from exc
    finally:
        workbook.close()

    body = "".join(parts) or '<p class="cn-preview-empty">（工作簿没有可预览的内容）</p>'
    if state[0]:
        body += _truncated_note()
    return _page(body, kind="Excel")


# ── 文档（docx）──


def _heading_level(style_name: str) -> int | None:
    """段落样式 → 标题层级（中英文 Word 样式名都识别）."""
    name = style_name.strip()
    lower = name.lower()
    if lower in {"title", "标题"}:
        return 1
    if lower in {"subtitle", "副标题"}:
        return 2
    match = _HEADING_RE.match(name)
    if match is not None:
        return min(max(int(match.group(1)), 1), 6)
    return None


def _list_kind(style_name: str) -> str | None:
    """列表样式 → ``ul`` / ``ol``（未识别返回 None）."""
    name = style_name.strip()
    lower = name.lower()
    if lower.startswith("list number") or name.startswith("列表编号"):
        return "ol"
    if lower.startswith("list bullet") or name in {"列表段落", "list paragraph"}:
        return "ul"
    return None


def _image_budget() -> dict[str, int]:
    return {"count": 0, "bytes": 0}


def _img_tag(blob: bytes, images: dict[str, int]) -> str:
    """内嵌图片 → ``<img data:>``（超过张数 / 字节上限后返回空串）."""
    if images["count"] >= MAX_IMAGES or images["bytes"] + len(blob) > MAX_IMAGE_BYTES:
        return ""
    images["count"] += 1
    images["bytes"] += len(blob)
    mime = _sniff_image_mime(blob)
    encoded = base64.b64encode(blob).decode("ascii")
    return f'<img src="data:{mime};base64,{encoded}" alt="">'


def _runs_html(run: Any, part: Any, images: dict[str, int]) -> str:
    """一个 run → 文本 + 图片（加粗 / 斜体 / 下划线），文本全部转义."""
    pieces: list[str] = []
    text = (run.text or "").replace("\t", "    ").replace("\x0b", "\n")
    if text:
        escaped = html.escape(text).replace("\n", "<br>")
        if getattr(run, "bold", None):
            escaped = f"<strong>{escaped}</strong>"
        if getattr(run, "italic", None):
            escaped = f"<em>{escaped}</em>"
        if getattr(run, "underline", None):
            escaped = f"<ins>{escaped}</ins>"
        pieces.append(escaped)
    for blob, _suffix in _iter_run_images(run, part):
        tag = _img_tag(blob, images)
        if tag:
            pieces.append(tag)
    return "".join(pieces)


def _table_html(table: Any) -> str:
    """表格 → ``<table>``（首行作表头，单元格内多段落以 ``<br>`` 连接）."""
    rows = list(table.rows)
    if not rows:
        return ""

    def row_html(row: Any, tag: str) -> str:
        cells = []
        for cell in row.cells:
            text = "\n".join(paragraph.text for paragraph in cell.paragraphs).strip()
            cells.append(f"<{tag}>{html.escape(text).replace(chr(10), '<br>')}</{tag}>")
        return f"<tr>{''.join(cells)}</tr>"

    head = f"<thead>{row_html(rows[0], 'th')}</thead>"
    body = "".join(row_html(row, "td") for row in rows[1:])
    return f'<table class="docx">{head}<tbody>{body}</tbody></table>'


def build_document_html(data: bytes) -> str:
    """docx 原件 → HTML（标题 / 段落 / 列表 / 表格 / 内嵌图片，ADR 0087 C2）."""
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise UnsupportedPreview(f"Word 原件无法解析：{exc}") from exc

    images = _image_budget()
    parts: list[str] = []
    size = 0
    list_open: str | None = None

    def close_list() -> None:
        nonlocal list_open
        if list_open is not None:
            parts.append(f"</{list_open}>")
            list_open = None

    try:
        for block in _iter_blocks(document):
            if size > MAX_HTML_CHARS:
                break
            if isinstance(block, Table):
                close_list()
                markup = _table_html(block)
                if markup:
                    parts.append(markup)
                    size += len(markup)
                continue
            if not isinstance(block, Paragraph):
                continue
            style_name = ""
            try:
                style = block.style
                style_name = (style.name if style is not None else "") or ""
            except Exception:
                style_name = ""
            inner = "".join(_runs_html(run, block.part, images) for run in block.runs)
            if not inner.strip():
                close_list()
                continue
            level = _heading_level(style_name)
            kind = _list_kind(style_name)
            if level is not None:
                close_list()
                markup = f"<h{level}>{inner}</h{level}>"
            elif kind is not None:
                if list_open != kind:
                    close_list()
                    parts.append(f"<{kind}>")
                    list_open = kind
                markup = f"<li>{inner}</li>"
            else:
                close_list()
                markup = f"<p>{inner}</p>"
            parts.append(markup)
            size += len(markup)
    except UnsupportedPreview:
        raise
    except Exception as exc:
        raise UnsupportedPreview(f"Word 原件无法解析：{exc}") from exc
    close_list()

    body = "".join(parts)
    if not body:
        body = '<p class="cn-preview-empty">（文档没有可见正文）</p>'
    if size > MAX_HTML_CHARS:
        body += _truncated_note()
    return _page(body, kind="Word")


def build_office_preview(content_type: str, mime: str, data: bytes) -> str:
    """Office 原件预览的唯一入口：按渲染族分派，旧版二进制格式一律拒绝."""
    if (mime or "").lower() in LEGACY_MIMES:
        raise UnsupportedPreview("旧版 Office 二进制格式（.xls / .doc）不支持在线预览，请下载后查看")
    if content_type == CONTENT_TYPE_XLSX:
        return build_spreadsheet_html(data)
    if content_type == CONTENT_TYPE_WORD:
        return build_document_html(data)
    raise UnsupportedPreview(f"不支持在线预览的内容类型：{content_type}")


__all__ = [
    "LEGACY_MIMES",
    "MAX_HTML_CHARS",
    "UnsupportedPreview",
    "build_document_html",
    "build_office_preview",
    "build_spreadsheet_html",
]

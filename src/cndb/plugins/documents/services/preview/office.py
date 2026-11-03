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
table.sheet { display: block; }
th, td { border: 1px solid #d7dee8; padding: 4px 8px; text-align: left; vertical-align: top; white-space: pre-wrap; }
th { background: #f1f5f9; font-weight: 600; }
/* 列号行吸附在顶部；行号列吸附在左侧（横向滚动时也可见） */
thead th { position: sticky; top: 0; z-index: 1; }
thead th.cn-sheet-corner { left: 0; z-index: 2; }
tbody th.cn-sheet-rownum { position: sticky; left: 0; z-index: 1; min-width: 40px;
  text-align: right; font-weight: 400; color: #64748b; background: #fafafa; }
img { max-width: 100%; height: auto; }
.cn-preview-title { font-size: 12px; color: #64748b; margin: 0 0 12px; }
/* 工作表分页：radio + label 实现无脚本标签页（沙箱内禁用 JS） */
.cn-sheet-tabs { position: relative; }
.cn-sheet-radio { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.cn-sheet-tabbar { display: flex; gap: 4px; overflow-x: auto; padding-bottom: 8px; margin-bottom: 12px;
  border-bottom: 1px solid #d7dee8; position: sticky; top: 0; background: #fff; z-index: 2; }
.cn-sheet-tab { flex: 0 0 auto; padding: 3px 12px; border: 1px solid transparent; border-radius: 6px;
  font-size: 13px; color: #64748b; cursor: pointer; white-space: nowrap; user-select: none; }
.cn-sheet-tab:hover { background: #f1f5f9; }
.cn-sheet-tab-count { color: #94a3b8; font-size: 11px; margin-left: 4px; }
.cn-sheet-panel { display: none; }
/* 可见性只由 :checked 决定（首屏也不需要常驻规则，否则切页时第一页不会隐藏） */
.cn-preview-empty, .cn-preview-note { color: #64748b; font-size: 12px; }
@media (prefers-color-scheme: dark) {
  body { background: #0f172a; color: #e2e8f0; }
  th { background: #1e293b; }
  th, td { border-color: #334155; }
  .cn-preview-title, .cn-preview-empty, .cn-preview-note { color: #94a3b8; }
  .cn-sheet-tabbar { background: #0f172a; border-color: #334155; }
  thead th { background: #1e293b; }
  tbody th.cn-sheet-rownum { background: #111827; color: #94a3b8; }
  .cn-sheet-tab { color: #94a3b8; }
  .cn-sheet-tab:hover { background: #1e293b; }
}
"""

#: 工作表页专用：整页铺满 iframe 高度，只有面板内部滚动（不留底部大空白）
_SHEET_PAGE_STYLE = """
html, body { height: 100%; }
body.cn-preview-sheet-page { display: flex; flex-direction: column; padding: 12px 20px 12px; }
body.cn-preview-sheet-page .cn-preview-title { flex: 0 0 auto; margin-bottom: 8px; }
.cn-sheet-tabs { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.cn-sheet-tabbar { flex: 0 0 auto; }
.cn-sheet-panels { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }
.cn-sheet-panel { flex: 1 1 auto; min-height: 0; overflow: auto; }
.cn-sheet-panels.is-single .cn-sheet-panel { display: block; }
body.cn-preview-sheet-page .cn-preview-note { flex: 0 0 auto; margin-top: 8px; }
"""

_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*(\d)$", re.IGNORECASE)


def _page(body: str, *, kind: str, extra_css: str = "", body_class: str = "") -> str:
    """套上自包含页面骨架（标题仅为格式提示，不含原件正文）."""
    class_attr = f' class="{body_class}"' if body_class else ""
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(kind)}预览</title><style>{_PAGE_STYLE}{extra_css}</style></head>"
        f'<body{class_attr}><p class="cn-preview-title">{html.escape(kind)}原件预览（只读）</p>{body}</body></html>'
    )


def _note(text: str) -> str:
    return f'<p class="cn-preview-note">{html.escape(text)}</p>'


def _truncated_note() -> str:
    return _note("内容超出预览上限，已截断；完整内容请下载原件查看。")


# ── 表格（xlsx）──


def _column_letters(index: int) -> str:
    """1 基列序号 → Excel 列名（1→A，26→Z，27→AA）."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


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
    """渲染一个工作表为表格 HTML（带 Excel 行列号）.

    ``budget`` 为跨表单元格余量，``state`` 为截断标记。行号取**原件真实行号**
    （整行为空的 Excel 行跳过，因此行号可能不连续），列号按 A/B/C… 生成。
    """
    rows: list[tuple[int, list[str]]] = []
    columns = 0
    for row_index, row in enumerate(
        ws.iter_rows(max_row=MAX_SHEET_ROWS, max_col=MAX_SHEET_COLS, values_only=True), start=1
    ):
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
        rows.append((row_index, cells))

    if not rows:
        return '<p class="cn-preview-empty">（空白工作表）</p>'

    letters = [_column_letters(index) for index in range(1, columns + 1)]
    head = (
        '<thead><tr><th class="cn-sheet-corner" scope="col"></th>'
        + "".join(f'<th scope="col">{letter}</th>' for letter in letters)
        + "</tr></thead>"
    )
    body_rows: list[str] = []
    for row_index, cells in rows:
        padded = cells + [""] * (columns - len(cells))
        body_rows.append(
            f'<tr><th class="cn-sheet-rownum" scope="row">{row_index}</th>'
            + "".join(f"<td>{html.escape(cell)}</td>" for cell in padded)
            + "</tr>"
        )
    return f'<table class="sheet">{head}<tbody>{"".join(body_rows)}</tbody></table>'


class _SheetTab:
    """一个工作表的标签页数据：名称 + 面板 HTML."""

    __slots__ = ("markup", "name")

    def __init__(self, name: str, markup: str) -> None:
        self.name = name
        self.markup = markup


def _spreadsheet_body(tabs: list[_SheetTab]) -> tuple[str, str]:
    """多工作表 → (标签页 HTML, 动态 CSS)；单表不渲染标签条，只出表格。

    分页用 ``radio + label`` 实现：预览在 ``sandbox``（禁脚本）中渲染，不能依赖 JS；
    每个工作表只在对应 radio 选中时显示（``:checked ~`` 兄弟选择器，Chrome 81 可用）。
    """
    if len(tabs) == 1:
        body = (
            '<div class="cn-sheet-panels is-single">'
            f'<section class="cn-sheet-panel" data-sheet="0">{tabs[0].markup}</section>'
            "</div>"
        )
        return body, ""

    radios: list[str] = []
    labels: list[str] = []
    panels: list[str] = []
    rules: list[str] = []
    dark_rules: list[str] = []
    for index, tab in enumerate(tabs):
        tab_id = f"cn-sheet-{index}"
        checked = " checked" if index == 0 else ""
        radios.append(f'<input class="cn-sheet-radio" type="radio" name="cn-sheet" id="{tab_id}"{checked}>')
        labels.append(
            f'<label class="cn-sheet-tab cn-sheet-tab-{index}" for="{tab_id}">{html.escape(tab.name)}</label>'
        )
        panels.append(
            f'<section class="cn-sheet-panel cn-sheet-panel-{index}" data-sheet="{index}">{tab.markup}</section>'
        )
        # 选中态：标签高亮 + 对应面板显示（无 JS 的纯 CSS 分页）
        selector = f"#{tab_id}:checked ~ .cn-sheet-tabbar .cn-sheet-tab-{index}"
        rules.append(f"{selector} {{ color: #1f2937; border-color: #d7dee8; background: #f1f5f9; font-weight: 600; }}")
        rules.append(f"#{tab_id}:checked ~ .cn-sheet-panels .cn-sheet-panel-{index} {{ display: block; }}")
        dark_rules.append(f"{selector} {{ color: #e2e8f0; border-color: #334155; background: #1e293b; }}")
    body = (
        '<div class="cn-sheet-tabs">'
        + "".join(radios)
        + '<div class="cn-sheet-tabbar" role="tablist">'
        + "".join(labels)
        + '</div><div class="cn-sheet-panels">'
        + "".join(panels)
        + "</div></div>"
    )
    extra_css = "".join(rules)
    if dark_rules:
        extra_css += "@media (prefers-color-scheme: dark) {" + "".join(dark_rules) + "}"
    return body, extra_css


def build_spreadsheet_html(data: bytes) -> str:
    """xlsx 原件 → 多工作表表格 HTML（ADR 0087 C1）.

    多工作表按**标签页分页**展示（一次只看一个表），标签条可横向滚动、吸附在顶部；
    单表不渲染标签条。分页用 CSS 实现，不依赖脚本（预览运行在 sandbox 中）。
    """
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise UnsupportedPreview(f"Excel 原件无法解析：{exc}") from exc

    tabs: list[_SheetTab] = []
    budget = [MAX_TOTAL_CELLS]
    state = [False]
    size = 0
    try:
        sheets = list(workbook.worksheets)
        for ws in sheets[:MAX_SHEETS]:
            markup = _sheet_html(ws, budget, state)
            tabs.append(_SheetTab(str(ws.title or "工作表"), markup))
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

    if not tabs:
        return _page('<p class="cn-preview-empty">（工作簿没有可预览的内容）</p>', kind="Excel")
    body, extra_css = _spreadsheet_body(tabs)
    if state[0]:
        body += _truncated_note()
    return _page(
        body,
        kind="Excel",
        extra_css=_SHEET_PAGE_STYLE + extra_css,
        body_class="cn-preview-sheet-page",
    )


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

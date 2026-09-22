"""报告模板 CRUD + 渲染端点."""

from __future__ import annotations

import io
import logging
import re
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.reports.models import OutputFormat, ReportTemplate
from cndb.plugins.reports.schemas import (
    RenderRequest,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 渲染超时保护（秒）
RENDER_TIMEOUT = 10

# ── Jinja2 安全沙箱 ──────────────────────────────────
# SandboxedEnvironment 默认禁用 __import__/open/exec/eval 等内置，
# 再额外收紧：移除 unsafe 过滤器 + 限制可用内置
_jinja_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

# 白名单过滤器（SandboxedEnvironment 已内置大部分，这里确认）
_ALLOWED_FILTERS = {
    "length",
    "sort",
    "reverse",
    "join",
    "trim",
    "upper",
    "lower",
    "default",
    "first",
    "last",
    "dictsort",
    "unique",
    "reject",
    "select",
    "map",
    "sum",
    "abs",
    "round",
    "int",
    "float",
    "string",
    "list",
    "title",
    "capitalize",
    "replace",
    "striptags",
    "wordcount",
    "indent",
    "format",
}

# 清理掉所有不安全过滤器，只保留白名单
_jinja_env.filters = {k: v for k, v in _jinja_env.filters.items() if k in _ALLOWED_FILTERS}

# 限制可用内置变量（禁掉 open/exec/eval/compile/__import__ 等）
# SandboxedEnvironment.globals 是 ChainMap，类型检查器可能不认可写操作
_unsafe_builtins = ("open", "exec", "eval", "compile", "__import__", "input", "print", "breakpoint", "exit", "quit")
for _name in _unsafe_builtins:
    _jinja_env.globals.__setitem__(_name, None)  # type: ignore[unsupported-operation]


def _validate_format(fmt: str) -> str:
    try:
        return OutputFormat(fmt).value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"不支持的输出格式: {fmt}") from exc


@router.get("", response_model=list[TemplateListResponse])
def list_templates(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[ReportTemplate]:
    stmt = select(ReportTemplate).order_by(ReportTemplate.id)
    return list(db.scalars(stmt).all())


def _resolve_table(db: Session, table_id: int | None) -> int | None:
    """可选校验 table_id 是否存在，存在则返回（用于模板归属校验）."""
    if table_id is None:
        return None
    from cndb.plugins.tables.models import DataTable

    if not db.get(DataTable, table_id):
        raise HTTPException(status_code=404, detail=f"数据表不存在 id={table_id}")
    return table_id


@router.post("", response_model=TemplateResponse, status_code=201)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    _validate_format(payload.output_format)
    _resolve_table(db, payload.table_id)
    try:
        _jinja_env.from_string(payload.template_content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模板语法错误: {exc}") from exc
    tpl = ReportTemplate(
        table_id=payload.table_id,
        name=payload.name,
        description=payload.description,
        output_format=payload.output_format,
        template_content=payload.template_content,
        parameters=[p.model_dump() for p in payload.parameters],
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    return tpl


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    # exclude_unset 会把显式设为 None 的字段也排除（因为等于默认值），
    # 所以改用显式迭代 model_fields 来检测用户真正设置了哪些字段
    ud: dict[str, Any] = {}
    for field_name in TemplateUpdate.model_fields:
        value = getattr(payload, field_name)
        # model_fields 里有但默认就是 None 的字段，exclude_unset 会排除
        # 这里我们只要用户显式传了就更新
        raw_value = payload.model_dump(exclude_unset=True).get(field_name, ...)
        if raw_value is not ...:
            ud[field_name] = value

    if "output_format" in ud:
        _validate_format(ud["output_format"])
    if "table_id" in ud:
        _resolve_table(db, ud["table_id"])
    if "template_content" in ud:
        try:
            _jinja_env.from_string(ud["template_content"])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"模板语法错误: {exc}") from exc
    for k, v in ud.items():
        if k == "parameters" and v is not None:
            # v 可能是 list[ParameterDef] 也可能是 list[dict]
            if v and hasattr(v[0], "model_dump"):
                setattr(tpl, k, [p.model_dump() for p in v])
            else:
                setattr(tpl, k, v)
        else:
            setattr(tpl, k, v)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> None:
    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(tpl)
    db.commit()


# ── 渲染器签名：renderer(rendered_text: str, ctx: dict[str, Any]) -> bytes ──


def _load_table_records(db: Session, table_id: int) -> tuple[Any, list[dict[str, Any]]]:
    """加载指定表的元数据和全部行数据.

    返回 (DataTable, records_list)，records 是扁平 dict 列表。
    """
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.records import list_rows

    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail=f"数据表不存在 id={table_id}")
    rows, _total = list_rows(db.bind, table, include_trashed=False, db=db)
    records = [r.get("data", r) for r in rows]
    return table, records


# ── 超时保护 ─────────────────────────────────────────


def _render_with_timeout(jinja_tmpl: Any, ctx: dict[str, Any], timeout: int = RENDER_TIMEOUT) -> str:
    """在线程中执行 Jinja2 渲染，支持超时中断.

    注意：Python 无法真正中断线程，超时后返回 TimeoutError 标记，
    但线程会继续运行到自然结束（这是 GIL 限制）。此处配合 SandboxedEnvironment
    保证即使超时线程也无法访问危险资源。
    """
    result: dict[str, str | Exception] = {}

    def _run() -> None:
        try:
            result["ok"] = jinja_tmpl.render(**ctx)
        except Exception as exc:  # pragma: no cover - 异常由调用方处理
            result["err"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        raise TimeoutError(f"模板渲染超时（{timeout}s），可能存在无限循环")
    if "err" in result:
        exc = result["err"]
        if isinstance(exc, Exception):
            raise exc
        raise RuntimeError(str(exc))
    return str(result.get("ok", ""))


# ── DOCX 渲染器 ──────────────────────────────────────


# Markdown 风格标题 / 粗体正则
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_CODE_RE = re.compile(r"`([^`]+)`")


def _render_docx(rendered_text: str, ctx: dict[str, Any]) -> bytes:
    """DOCX 渲染：支持 Markdown 风格标题 + 加粗 + 代码.

    ctx 保留签名一致性，未来可用于渲染 data table 等结构化元素.
    """
    from docx import Document
    from docx.shared import Pt

    _ = ctx  # 预留：未来可用于生成 data table 等结构化元素
    doc = Document()

    for raw_line in rendered_text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            doc.add_paragraph("")
            continue

        m = _MD_HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 9)
            text = m.group(2).strip()
            try:
                doc.add_heading(text, level=level)
            except (KeyError, ValueError):
                # 某些 Word 版本没有 Heading 5+
                p = doc.add_paragraph()
                run = p.add_run(text)
                run.bold = True
                run.font.size = Pt(16 - level)
            continue

        # 普通段落，处理粗体和代码
        p = doc.add_paragraph()
        _add_rich_runs(p, line)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _add_rich_runs(paragraph: Any, text: str) -> None:
    """在 docx 段落中按 **bold** 和 `code` 分段添加 Run."""
    # 先用代码段切分（优先级高）
    code_parts = re.split(r"(`[^`]+`)", text)
    for part in code_parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Courier New"
            continue
        # 再按粗体切分
        bold_parts = _MD_BOLD_RE.split(part)
        for i, bp in enumerate(bold_parts):
            if i % 2 == 1:
                # 奇数位是粗体内容
                run = paragraph.add_run(bp)
                run.bold = True
            elif bp:
                paragraph.add_run(bp)


# ── PDF 渲染器 ───────────────────────────────────────


_pdf_font_state: list[bool] = [False]


def _ensure_pdf_font() -> None:
    """注册 reportlab 中文字体（懒加载，避免无 PDF 需求时的开销）."""
    if _pdf_font_state[0]:
        return
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_candidates = [
            ("NotoSansSC-Regular", "NotoSansSC-Regular.otf"),
            ("NotoSansSC", "NotoSansSC.ttf"),
            ("WenQuanYiMicroHei", "WenQuanYiMicroHei.ttf"),
            ("WenQuanYiZenHei", "WenQuanYiZenHei.ttf"),
        ]
        registered = False
        for font_name, font_file in font_candidates:
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_file))
                registered = True
                break
            except Exception:
                continue
        if not registered:
            try:
                pdfmetrics.registerFont(TTFont("STSong-Light", "STSong-Light.ttf"))
                registered = True
            except Exception:
                pass
        if not registered:
            logger.warning("reportlab 中文字体不可用，PDF 中文字符可能显示异常")
    except Exception:
        logger.debug("reportlab 字体注册跳过", exc_info=True)
    _pdf_font_state[0] = True


def _render_pdf(rendered_text: str, ctx: dict[str, Any]) -> bytes:
    """PDF 渲染：Platypus 框架 + 自动分页 + 页眉页脚."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    _ensure_pdf_font()
    buf = io.BytesIO()
    title = ctx.get("table_name", "Report")

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        spaceAfter=4,
    )
    heading_styles = {
        1: ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, leading=22, spaceBefore=12, spaceAfter=8),
        2: ParagraphStyle("H2", parent=styles["Heading2"], fontSize=15, leading=19, spaceBefore=10, spaceAfter=6),
        3: ParagraphStyle("H3", parent=styles["Heading3"], fontSize=13, leading=16, spaceBefore=8, spaceAfter=4),
    }

    story: list[Any] = []
    table_buffer: list[list[str]] = []
    in_table = False

    for raw_line in rendered_text.split("\n"):
        line = raw_line.rstrip()

        # 表格行：以 | 分隔
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if not in_table:
                in_table = True
                table_buffer = []
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            table_buffer.append(cells)
            continue
        elif in_table:
            # 表格结束，提交表格
            if table_buffer:
                story.append(_make_pdf_table(table_buffer))
            in_table = False
            table_buffer = []
            # 继续处理当前这行

        # 空行
        if not line.strip():
            story.append(Spacer(1, 6))
            continue

        # 标题行
        m = _MD_HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            text = m.group(2).strip()
            style = heading_styles.get(level, heading_styles[3])
            story.append(Paragraph(_pdf_escape(text), style))
            continue

        # 换页标记
        if line.strip() == "---PAGE---":
            story.append(PageBreak())
            continue

        # 普通段落（处理粗体）
        story.append(Paragraph(_pdf_markdown_to_rml(line), body_style))

    # 收尾：提交剩余表格
    if in_table and table_buffer:
        story.append(_make_pdf_table(table_buffer))

    # 分页回调（页眉 + 页脚页码）
    def _on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        # 页眉
        canvas.drawString(50, A4[1] - 30, str(title))
        canvas.drawRightString(A4[0] - 50, A4[1] - 30, cndb_report_header())
        # 页脚
        canvas.drawCentredString(A4[0] / 2, 30, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=50,
        bottomMargin=50,
        title=str(title),
    )
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf.getvalue()


def cndb_report_header() -> str:
    """PDF 页眉右侧固定文本."""
    import datetime as dt

    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _pdf_escape(text: str) -> str:
    """转义 reportlab RML 特殊字符."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_markdown_to_rml(text: str) -> str:
    """将 Markdown 粗体/代码转为 reportlab RML."""
    escaped = _pdf_escape(text)
    escaped = _MD_BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _MD_CODE_RE.sub(r"<font name='Courier'><i>\1</i></font>", escaped)
    return escaped


def _make_pdf_table(rows: list[list[str]]) -> Any:
    """构造 reportlab Table（带表头样式 + 跨页重复）."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    if not rows:
        return Table([[]])
    # 确保每行等宽
    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]
    table = Table(norm_rows, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EEF5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1A5276")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
    ]
    table.setStyle(TableStyle(style))
    return table


def _render_xlsx(rendered_text: str, ctx: dict[str, Any]) -> bytes:
    """XLSX 渲染：按 records_by_table 中每张表创建独立 Sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    sheet_created = False
    sheets_data: dict[str, list[dict[str, Any]]] = {}

    # 收集所有表的数据：主表 + extra 表
    # 即使 records 为空也要创建 Sheet（表名有意义时）
    records = ctx.get("records", [])
    table_name = ctx.get("table_name", "Sheet1")
    if table_name and table_name != "Sheet1":
        sheets_data[table_name] = records  # 允许空 records，仍创建 Sheet

    records_by_table = ctx.get("records_by_table", {})
    for tname, trecords in records_by_table.items():
        if tname not in sheets_data:
            sheets_data[tname] = trecords  # 同上，允许空 records

    # 去非法 Sheet 名字符，截断到 31 字符
    def _safe_sheet_name(name: str) -> str:
        safe = "".join(c for c in name if c not in "*?:/\\[]").strip()
        return safe[:31] or "Sheet"

    for sheet_name, rows_data in sheets_data.items():
        if not sheet_created:
            ws = wb.active
            assert ws is not None, "Workbook should always have at least one active sheet"
            ws.title = _safe_sheet_name(sheet_name)
            sheet_created = True
        else:
            ws = wb.create_sheet(title=_safe_sheet_name(sheet_name))

        # 收集所有字段名
        field_names: list[str] = []
        for r in rows_data:
            for k in r:
                if k not in field_names:
                    field_names.append(k)
        # 过滤系统字段
        skip_keys = {"id", "created_at", "updated_at", "created_by", "updated_by"}
        field_names = [f for f in field_names if f not in skip_keys]

        # 写表头
        for col_idx, fname in enumerate(field_names, start=1):
            cell = ws.cell(row=1, column=col_idx, value=fname)
            cell.font = Font(bold=True)
        # 冻结首行
        ws.freeze_panes = "A2"

        # 写数据
        for row_idx, row_data in enumerate(rows_data, start=2):
            for col_idx, fname in enumerate(field_names, start=1):
                value = row_data.get(fname, "")
                # reportlab/openpyxl 不接受 None，转空串
                if value is None:
                    value = ""
                elif isinstance(value, (list, dict)):
                    value = str(value)
                ws.cell(row=row_idx, column=col_idx, value=value)

        # 自动列宽（估算）
        for col_idx, fname in enumerate(field_names, start=1):
            max_len = len(str(fname))
            for row_data in rows_data:
                v = row_data.get(fname, "")
                if v is not None:
                    vlen = len(str(v))
                    max_len = max(max_len, vlen)
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)  # type: ignore[union-attr]

    # 如果没有任何数据，保留默认 Sheet
    if not sheet_created:
        ws = wb.active
        assert ws is not None, "Workbook should always have at least one active sheet"
        ws.cell(row=1, column=1, value=rendered_text)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


_FORMAT_RENDERERS: dict[str, Any] = {
    OutputFormat.DOCX: _render_docx,
    OutputFormat.PDF: _render_pdf,
    OutputFormat.XLSX: _render_xlsx,
}

_CONTENT_TYPES: dict[str, str] = {
    OutputFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    OutputFormat.PDF: "application/pdf",
    OutputFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.post("/{template_id}/render")
def render_report(
    template_id: int,
    payload: RenderRequest,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    from cndb.plugins.tables.models import DataTable

    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")

    # 加载主表
    table, records = _load_table_records(db, payload.table_id)

    # 加载 extra 表（如有）
    records_by_table: dict[str, list[dict[str, Any]]] = {}
    seen_table_ids: set[int] = {payload.table_id}
    extra_table_ids = list(dict.fromkeys(payload.extra_table_ids))  # 去重保序
    for etid in extra_table_ids:
        if etid in seen_table_ids:
            continue
        seen_table_ids.add(etid)
        etable = db.get(DataTable, etid)
        if etable is None:
            raise HTTPException(status_code=404, detail=f"额外数据表不存在 id={etid}")
        _, erecords = _load_table_records(db, etid)
        records_by_table[etable.name] = erecords

    # 构建渲染上下文
    ctx: dict[str, Any] = {
        "records": records,
        "table_name": table.name,
        "params": payload.params,
        "records_by_table": records_by_table,
    }

    # Jinja2 渲染（带超时保护 + 安全沙箱）
    try:
        jinja_tmpl = _jinja_env.from_string(tpl.template_content)
        rendered_text = _render_with_timeout(jinja_tmpl, ctx, timeout=RENDER_TIMEOUT)
    except TimeoutError as exc:
        logger.warning("模板渲染超时 template_id=%s: %s", template_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("模板渲染失败 template_id=%s: %s", template_id, exc)
        # Jinja2 SecurityError 需要特殊消息
        from jinja2.sandbox import SecurityError

        if isinstance(exc, SecurityError):
            raise HTTPException(status_code=400, detail=f"模板安全错误: {exc}") from exc
        raise HTTPException(status_code=400, detail=f"模板渲染失败: {exc}") from exc

    # 调用格式渲染器（传入 rendered_text + 完整 ctx）
    renderer = _FORMAT_RENDERERS.get(tpl.output_format)
    if renderer is None:
        raise HTTPException(status_code=400, detail=f"不支持的输出格式: {tpl.output_format}")
    try:
        file_bytes = renderer(rendered_text, ctx)
    except Exception as exc:
        logger.error("文件生成失败 template_id=%s format=%s: %s", template_id, tpl.output_format, exc)
        raise HTTPException(status_code=500, detail=f"文件生成失败: {exc}") from exc

    content_type = _CONTENT_TYPES[tpl.output_format]
    filename = "report." + tpl.output_format
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]

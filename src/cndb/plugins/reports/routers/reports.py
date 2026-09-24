"""报告模板 CRUD + 渲染端点."""

from __future__ import annotations

import datetime as dt
import io
import logging
import re
import threading
from typing import Any, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.reports.models import OutputFormat, ReportTemplate, ThemeStyle
from cndb.plugins.reports.schemas import (
    RenderRequest,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)
from cndb.plugins.reports.themes import ThemePreset, get_theme_preset

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
    "select",
    "reject",
    "selectattr",
    "rejectattr",
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


# ── 统计函数 ──────────────────────────────────
# 这两个函数在 SandboxedEnvironment.globals 注册，模板内可直接调用。
# 输入 records 是 list[dict]，field 是字段名。返回的都是纯数据结构（dict / list[dict]），
# 方便 Jinja2 用 .sum/.count 之类的属性访问。


def _coerce_numeric(value: Any) -> float | None:
    """把字段值强转为数字；None / 非数字 / 空串返回 None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stats(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """对 records 的 field 列做聚合，返回 {count, sum, avg, min, max, non_empty}.

    count/sum/avg/min/max 只统计可解析为数值的行；
    non_empty 统计原始值非空（非 None 且非空串）的行数，可用于文本字段计数。
    """
    raw_values = [r.get(field) for r in records]
    nums = [v for v in (_coerce_numeric(x) for x in raw_values) if v is not None]
    non_empty = sum(1 for v in raw_values if v is not None and v != "")
    if not nums:
        return {"count": 0, "sum": 0, "avg": 0, "min": None, "max": None, "non_empty": non_empty}
    total = sum(nums)
    return {
        "count": len(nums),
        "sum": total,
        "avg": total / len(nums),
        "min": min(nums),
        "max": max(nums),
        "non_empty": non_empty,
    }


def _group_stats(
    records: list[dict[str, Any]],
    key_field: str,
    value_field: str,
) -> list[dict[str, Any]]:
    """按 key_field 分组，对 value_field 做聚合，返回 list[dict with key + stats]."""
    groups: dict[Any, list[Any]] = {}
    for r in records:
        k = r.get(key_field)
        if k not in groups:
            groups[k] = []
        groups[k].append(r.get(value_field))
    result: list[dict[str, Any]] = []
    for key, vals in groups.items():
        nums = [v for v in (_coerce_numeric(v) for v in vals) if v is not None]
        if nums:
            total = sum(nums)
            result.append(
                {
                    "key": key,
                    "count": len(nums),
                    "sum": total,
                    "avg": total / len(nums),
                    "min": min(nums),
                    "max": max(nums),
                }
            )
        else:
            result.append({"key": key, "count": 0, "sum": 0, "avg": 0, "min": None, "max": None})
    return result


_jinja_env.globals.__setitem__("stats", _stats)  # type: ignore[unsupported-operation]
_jinja_env.globals.__setitem__("group_stats", _group_stats)  # type: ignore[unsupported-operation]


def _validate_format(fmt: str) -> str:
    try:
        return OutputFormat(fmt).value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"不支持的输出格式: {fmt}") from exc


def _validate_theme(theme: str) -> str:
    """校验主题风格值，非法值 400."""
    try:
        return ThemeStyle(theme).value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"不支持的主题风格: {theme}") from exc


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


def _resolve_extra_tables(db: Session, extra_table_ids: list[int]) -> list[int]:
    """校验额外引用表 id 列表（去重保序），任一不存在则 404；渲染时的 READ 权限在渲染端校验."""
    from cndb.plugins.tables.models import DataTable

    resolved: list[int] = []
    for tid in dict.fromkeys(extra_table_ids):
        if not db.get(DataTable, tid):
            raise HTTPException(status_code=404, detail=f"额外引用表不存在 id={tid}")
        resolved.append(tid)
    return resolved


@router.post("", response_model=TemplateResponse, status_code=201)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    _validate_format(payload.output_format)
    _validate_theme(payload.theme)
    _resolve_table(db, payload.table_id)
    extra_ids = _resolve_extra_tables(db, payload.extra_table_ids)
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
        extra_table_ids=extra_ids,
        theme=payload.theme,
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
    if "theme" in ud and ud["theme"] is not None:
        ud["theme"] = _validate_theme(ud["theme"])
    if "table_id" in ud:
        _resolve_table(db, ud["table_id"])
    if "extra_table_ids" in ud and ud["extra_table_ids"] is not None:
        ud["extra_table_ids"] = _resolve_extra_tables(db, ud["extra_table_ids"])
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


def _load_table_records(db: Session, table_id: int, user: User) -> tuple[Any, list[dict[str, Any]]]:
    """加载指定表的元数据和全部行数据（带 READ 权限校验 + 字段隐藏）.

    list_rows 默认 limit=100，报表必须拿到完整数据，这里按页循环取全量。
    返回 (DataTable, records_list)，records 是扁平 dict 列表。
    """
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.access import TableAction, check_action
    from cndb.plugins.tables.services.core.records import list_rows

    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail=f"数据表不存在 id={table_id}")
    if not check_action(db, table, user, TableAction.READ):
        raise HTTPException(status_code=403, detail="无权访问该数据表")
    page_size = 500
    offset = 0
    records: list[dict[str, Any]] = []
    while True:
        rows, total = list_rows(db.bind, table, include_trashed=False, offset=offset, limit=page_size, db=db, user=user)
        records.extend(r.get("data", r) for r in rows)
        offset += len(rows)
        if not rows or offset >= total:
            break
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
_MD_TABLE_SEP_RE = re.compile(r"^:?-{3,}:?$")


def _render_docx(rendered_text: str, ctx: dict[str, Any], theme: str = ThemeStyle.MINIMAL.value) -> bytes:
    """DOCX 渲染：支持 Markdown 风格标题 + 加粗 + 代码 + 表格，并按主题风格应用文字与格式.

    ctx 保留签名一致性，未来可用于渲染 data table 等结构化元素.
    """
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    from docx.styles.style import ParagraphStyle as DocxParagraphStyle

    preset = get_theme_preset(theme)
    _ = ctx  # 预留：未来可用于生成 data table 等结构化元素
    doc = Document()

    # 全局正文样式（Normal）应用主题正文字体/字号，含中文东亚字体映射
    normal = cast(DocxParagraphStyle, doc.styles["Normal"])
    normal.font.name = preset.body_font
    normal.font.size = Pt(preset.body_size)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), preset.body_font)

    def _apply_run_font(run: Any, font: str, size: float | None = None, color: str | None = None) -> None:
        """给 run 设置字体名（含东亚映射）、字号、颜色."""
        run.font.name = font
        run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font)
        if size is not None:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))

    def _add_themed_heading(text: str, level: int) -> None:
        """按主题添加标题段落；主题色/字号/字体应用于标题 run."""
        idx = min(level, 3) - 1
        try:
            p = doc.add_heading(text, level=level)
        except (KeyError, ValueError):
            # 某些 Word 版本没有 Heading 5+
            p = doc.add_paragraph()
            run = p.add_run(text)
            run.bold = True
            _apply_run_font(run, preset.heading_font, preset.heading_sizes[idx], preset.heading_colors[idx])
            return
        for run in p.runs:
            _apply_run_font(run, preset.heading_font, preset.heading_sizes[idx], preset.heading_colors[idx])

    table_buffer: list[str] = []
    in_table = False

    def _is_table_row(line: str) -> bool:
        s = line.strip()
        return s.startswith("|") and s.endswith("|")

    def _flush_table() -> None:
        """把缓冲的 markdown 表格行写入 docx 表格对象（跳过分隔行，首行加粗 + 主题底纹）."""
        nonlocal in_table, table_buffer
        rows = [[c.strip() for c in raw.strip().strip("|").split("|")] for raw in table_buffer if raw.strip()]
        # 跳过 markdown 分隔行（| --- | :---: |）
        rows = [r for r in rows if not all(_MD_TABLE_SEP_RE.match(c or "-") for c in r)]
        if rows:
            max_cols = max(len(r) for r in rows)
            norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]
            t = doc.add_table(rows=len(norm_rows), cols=max_cols)
            t.style = "Table Grid"
            for i, row_cells in enumerate(norm_rows):
                for j, cell_text in enumerate(row_cells):
                    cell = t.cell(i, j)
                    p = cell.paragraphs[0]
                    if i == 0:
                        run = p.add_run(cell_text)
                        run.bold = True
                        # 表头主题：底纹 + 文字色
                        shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
                        shd.set(qn("w:val"), "clear")
                        shd.set(qn("w:fill"), preset.table_header_bg.lstrip("#"))
                        cell._tc.get_or_add_tcPr().append(shd)
                        _apply_run_font(run, preset.body_font, color=preset.table_header_color)
                    else:
                        _add_rich_runs(p, cell_text, preset.table_body_font, preset.code_font)
        in_table = False
        table_buffer = []

    for raw_line in rendered_text.split("\n"):
        line = raw_line.rstrip()

        if _is_table_row(line):
            if not in_table:
                in_table = True
                table_buffer = []
            table_buffer.append(line)
            continue
        if in_table:
            _flush_table()

        if not line.strip():
            doc.add_paragraph("")
            continue

        m = _MD_HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 9)
            text = m.group(2).strip()
            _add_themed_heading(text, level)
            continue

        # 换页标记
        if line.strip() == "---PAGE---":
            doc.add_page_break()
            continue

        # 普通段落，处理粗体和代码
        p = doc.add_paragraph()
        _add_rich_runs(p, line, preset.body_font, preset.code_font)

    # 收尾：提交剩余表格
    if in_table:
        _flush_table()

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _add_rich_runs(paragraph: Any, text: str, body_font: str = "Calibri", code_font: str = "Courier New") -> None:
    """在 docx 段落中按 **bold** 和 `code` 分段添加 Run，正文/代码分别应用主题字体."""
    # 先用代码段切分（优先级高）
    code_parts = re.split(r"(`[^`]+`)", text)
    for part in code_parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = code_font
            continue
        # 再按粗体切分
        bold_parts = _MD_BOLD_RE.split(part)
        for i, bp in enumerate(bold_parts):
            if i % 2 == 1:
                # 奇数位是粗体内容
                run = paragraph.add_run(bp)
                run.bold = True
                run.font.name = body_font
            elif bp:
                run = paragraph.add_run(bp)
                run.font.name = body_font


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
                logger.debug("备用字体 STSong-Light 注册失败", exc_info=True)
        if not registered:
            logger.warning("reportlab 中文字体不可用，PDF 中文字符可能显示异常")
    except Exception:
        logger.debug("reportlab 字体注册跳过", exc_info=True)
    _pdf_font_state[0] = True


def _render_pdf(rendered_text: str, ctx: dict[str, Any], theme: str = ThemeStyle.MINIMAL.value) -> bytes:
    """PDF 渲染：Platypus 框架 + 自动分页 + 页眉页脚，按主题应用字号与颜色.

    注意：reportlab 仅使用已注册字体（Helvetica 系列），主题预设只取字号/颜色，不改字体名.
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    _ensure_pdf_font()
    preset = get_theme_preset(theme)
    buf = io.BytesIO()
    title = ctx.get("table_name", "Report")

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=preset.body_size,
        leading=preset.body_size * 1.5,
        spaceAfter=4,
    )
    heading_styles = {
        i + 1: ParagraphStyle(
            f"H{i + 1}",
            parent=styles[f"Heading{i + 1}"],
            fontSize=preset.heading_sizes[i],
            leading=preset.heading_sizes[i] * 1.25,
            spaceBefore=12 - i * 2,
            spaceAfter=8 - i * 2,
            textColor=HexColor(preset.heading_colors[i]),
        )
        for i in range(3)
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
                story.append(_make_pdf_table(table_buffer, preset))
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
        story.append(_make_pdf_table(table_buffer, preset))

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


def _pdf_table_style_cmds(preset: ThemePreset) -> list[tuple[Any, ...]]:
    """按主题预设构造 PDF 表格样式命令列表（表头底色/文字色 + 斑马纹 + 网格）."""
    from reportlab.lib import colors

    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(preset.table_header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(preset.table_header_color)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
    ]


def _make_pdf_table(rows: list[list[str]], preset: ThemePreset | None = None) -> Any:
    """构造 reportlab Table（带主题表头样式 + 跨页重复）."""
    from reportlab.platypus import Table, TableStyle

    if not rows:
        return Table([[]])
    # 确保每行等宽
    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]
    table = Table(norm_rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(_pdf_table_style_cmds(preset or get_theme_preset("minimal"))))
    return table


def _render_xlsx(rendered_text: str, ctx: dict[str, Any], theme: str = ThemeStyle.MINIMAL.value) -> bytes:
    """XLSX 渲染：按 records_by_table 中每张表创建独立 Sheet.

    theme 参数保留签名统一；XLSX 为数据导向，不应用主题样式.
    """
    _ = theme
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.worksheet.worksheet import Worksheet

    wb = Workbook()
    sheet_created = False
    used_names: set[str] = set()
    sheets: list[tuple[str, list[dict[str, Any]]]] = []

    # 收集所有表的数据：主表 + extra 表（list 而非 dict，避免同名表互相覆盖丢数据）
    # 即使 records 为空也要创建 Sheet（表名有意义时）
    records = ctx.get("records", [])
    table_name = ctx.get("table_name", "Sheet1")
    if table_name and table_name != "Sheet1":
        sheets.append((table_name, records))

    for tname, trecords in ctx.get("records_by_table", {}).items():
        sheets.append((tname, trecords))

    # 去非法 Sheet 名字符，截断到 31 字符
    def _safe_sheet_name(name: str) -> str:
        safe = "".join(c for c in name if c not in "*?:/\\[]").strip()
        return safe[:31] or "Sheet"

    # 同名表（如跨工作区）追加序号后缀，保证不重名也不丢数据
    def _unique_sheet_name(name: str) -> str:
        base = _safe_sheet_name(name)
        candidate = base
        n = 1
        while candidate in used_names:
            suffix = str(n)
            candidate = f"{base[: 31 - len(suffix)]}{suffix}"
            n += 1
        used_names.add(candidate)
        return candidate

    for raw_name, rows_data in sheets:
        sheet_name = _unique_sheet_name(raw_name)
        if not sheet_created:
            ws = cast(Worksheet, wb.active)  # Workbook 始终有 active sheet
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
        ws = cast(Worksheet, wb.active)  # Workbook 始终有 active sheet
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


def _render_filename(template_name: str, fmt: str) -> str:
    """构造带生成时间戳的下载文件名：{模板名}_{YYYYMMDD_HHMMSS}.{ext}，便于区分不同批次."""
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[\\/:*?"<>|]', "_", template_name).strip() or "report"
    return f"{safe}_{ts}.{fmt}"


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

    # 加载主表（带 READ 权限校验 + 字段隐藏）
    table, records = _load_table_records(db, payload.table_id, _current_user)

    # 加载 extra 表（如有，同样带权限校验）
    # 合并模板持久化的 extra_table_ids（模板自包含，请求可不重复传）与请求临时指定的，去重保序
    records_by_table: dict[str, list[dict[str, Any]]] = {}
    seen_table_ids: set[int] = {payload.table_id}
    extra_table_ids = list(dict.fromkeys([*(tpl.extra_table_ids or []), *payload.extra_table_ids]))
    for etid in extra_table_ids:
        if etid in seen_table_ids:
            continue
        seen_table_ids.add(etid)
        etable = db.get(DataTable, etid)
        if etable is None:
            raise HTTPException(status_code=404, detail=f"额外数据表不存在 id={etid}")
        _, erecords = _load_table_records(db, etid, _current_user)
        records_by_table[etable.name] = erecords

    # 构建渲染上下文
    ctx: dict[str, Any] = {
        "records": records,
        "table_name": table.name,
        "params": payload.params,
        "records_by_table": records_by_table,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
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
        file_bytes = renderer(rendered_text, ctx, tpl.theme or ThemeStyle.MINIMAL.value)
    except Exception as exc:
        logger.error("文件生成失败 template_id=%s format=%s: %s", template_id, tpl.output_format, exc)
        raise HTTPException(status_code=500, detail=f"文件生成失败: {exc}") from exc

    content_type = _CONTENT_TYPES[tpl.output_format]
    filename = _render_filename(tpl.name, tpl.output_format)
    quoted = quote(filename)
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers={
            # ASCII fallback + RFC 5987 filename*（中文模板名）
            "Content-Disposition": f"attachment; filename=\"report.{tpl.output_format}\"; filename*=UTF-8''{quoted}"
        },
    )


__all__ = ["router"]

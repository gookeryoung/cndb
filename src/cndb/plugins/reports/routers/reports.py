"""报告模板 CRUD + 渲染端点."""

from __future__ import annotations

import io
import logging
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

_jinja_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


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
    for field_name in payload.model_fields:
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


def _render_docx(content: str) -> bytes:
    from docx import Document

    doc = Document()
    for paragraph in content.split(chr(10)):
        doc.add_paragraph(paragraph)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _render_pdf(content: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _width, height = A4
    y = height - 50
    for line in content.split(chr(10)):
        if y < 50:
            c.showPage()
            y = height - 50
        c.drawString(50, y, line)
        y -= 15
    c.save()
    buf.seek(0)
    return buf.getvalue()


def _render_xlsx(content: str) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb[wb.sheetnames[0]]
    for row_idx, line in enumerate(content.split(chr(10)), start=1):
        if not line.strip():
            continue
        cells = line.split(chr(9))
        for col_idx, cell in enumerate(cells, start=1):
            ws.cell(row=row_idx, column=col_idx, value=cell)
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
    from cndb.plugins.tables.records import list_rows

    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    table = db.get(DataTable, payload.table_id)
    if not table:
        raise HTTPException(status_code=404, detail="数据表不存在")
    rows, _total = list_rows(db.bind, table, include_trashed=False, db=db)

    records = [r.get("data", r) for r in rows]
    ctx = {"records": records, "table_name": table.name, "params": payload.params}
    try:
        jinja_tmpl = _jinja_env.from_string(tpl.template_content)
        rendered_text = jinja_tmpl.render(**ctx)
    except Exception as exc:
        logger.warning("模板渲染失败 template_id=%s: %s", template_id, exc)
        raise HTTPException(status_code=400, detail=f"模板渲染失败: {exc}") from exc
    renderer = _FORMAT_RENDERERS.get(tpl.output_format)
    if renderer is None:
        raise HTTPException(status_code=400, detail=f"不支持的输出格式: {tpl.output_format}")
    try:
        file_bytes = renderer(rendered_text)
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

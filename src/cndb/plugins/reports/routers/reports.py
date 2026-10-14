"""报告模板 CRUD + 渲染端点（HTTP 层）。

输出格式的具体实现见 cndb.plugins.reports.renderers。"""

from __future__ import annotations

import datetime as dt
import io
import logging
import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.reports.jinja import _jinja_env
from cndb.plugins.reports.models import OutputFormat, ReportTemplate, ThemeStyle
from cndb.plugins.reports.renderers import _FORMAT_RENDERERS
from cndb.plugins.reports.renderers.context import (
    RENDER_TIMEOUT,
    _flatten_for_report,
    _load_table_records,
    _render_with_timeout,
)
from cndb.plugins.reports.renderers.docx import _add_rich_runs, _render_docx
from cndb.plugins.reports.renderers.html import _html_escape, _html_rich_text, _render_html
from cndb.plugins.reports.renderers.pdf import (
    _make_pdf_table,
    _pdf_escape,
    _pdf_markdown_to_rml,
    _pdf_table_style_cmds,
    _render_pdf,
    cndb_report_header,
)
from cndb.plugins.reports.renderers.pdf_fonts import (
    _cjk_font_candidates,
    _ensure_pdf_font,
    _is_cjk_family,
    _pdf_font_state,
    _run_command,
)
from cndb.plugins.reports.renderers.xlsx import _render_xlsx
from cndb.plugins.reports.schemas import (
    RenderRequest,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)
from cndb.plugins.reports.services.stats import _coerce_numeric, _group_stats, _stats
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_action,
    check_workspace_permission,
)
from cndb.plugins.workspaces.models import WorkspaceRole

logger = logging.getLogger(__name__)
router = APIRouter()


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


def _authorize_template_workspace(db: Session, workspace_id: int, user: User) -> None:
    """校验用户对工作区的 VIEWER 级最低权限（模板归属工作区时调用）.

    Args:
        db: 数据库会话
        workspace_id: 目标工作区 ID
        user: 当前用户

    Raises:
        HTTPException(404): 工作区不存在
        HTTPException(403): 用户不是工作区成员
    """
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)


def _authorize_table_for_template(db: Session, table_id: int, user: User, action: TableAction) -> None:
    """校验用户对数据表的表级权限（模板绑定到具体表时调用）.

    Args:
        db: 数据库会话
        table_id: 目标表 ID
        user: 当前用户
        action: 需要的表级动作（通常 READ 或 EDIT_VIEWS）

    Raises:
        HTTPException(404): 表不存在
        HTTPException(403): 用户无对应表级权限
    """
    from cndb.plugins.tables.models import DataTable

    dt = db.get(DataTable, table_id)
    if dt is None:
        raise HTTPException(status_code=404, detail=f"数据表不存在 id={table_id}")
    if not check_action(db, dt, user, action):
        raise HTTPException(status_code=403, detail="无权访问该数据表")


def _authorize_template_access(db: Session, tpl: ReportTemplate, user: User, action: TableAction) -> None:
    """校验用户对模板的访问权限.

    权限解析优先级：
      1. 模板绑定 table_id → 走表级 action 校验
      2. 模板有 workspace_id（无 table_id） → 走工作区级 VIEWER 校验
      3. 两者都无 → 通用模板，已登录用户均可访问
    """
    if tpl.table_id is not None:
        _authorize_table_for_template(db, tpl.table_id, user, action)
        return
    if tpl.workspace_id is not None:
        _authorize_template_workspace(db, tpl.workspace_id, user)
        return
    # 通用模板，已登录用户均可访问 — 到此已证明 user 非 None（由 get_current_user 保证）


@router.get("", response_model=list[TemplateListResponse])
def list_templates(
    workspace_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReportTemplate]:
    """列出报表模板；传 workspace_id 时仅返回归属该工作区的模板（需是工作区成员）.

    不传 workspace_id 时返回当前用户有权访问的全部模板（归属表有 READ 权限或
    归属工作区有 VIEWER 角色）。
    """
    if workspace_id is not None:
        _authorize_template_workspace(db, workspace_id, current_user)
        stmt = select(ReportTemplate).where(ReportTemplate.workspace_id == workspace_id).order_by(ReportTemplate.id)
        return list(db.scalars(stmt).all())

    # 无 workspace_id：筛选用户有权访问的模板
    all_templates = list(db.scalars(select(ReportTemplate).order_by(ReportTemplate.id)).all())
    authorized: list[ReportTemplate] = []
    for tpl in all_templates:
        try:
            _authorize_template_access(db, tpl, current_user, TableAction.READ)
            authorized.append(tpl)
        except HTTPException:
            continue
    return authorized


def _resolve_table(db: Session, table_id: int | None) -> int | None:
    """可选校验 table_id 是否存在，存在则返回（用于模板归属校验）."""
    if table_id is None:
        return None
    from cndb.plugins.tables.models import DataTable

    if not db.get(DataTable, table_id):
        raise HTTPException(status_code=404, detail=f"数据表不存在 id={table_id}")
    return table_id


def _resolve_workspace_id(db: Session, workspace_id: int | None, table_id: int | None) -> int | None:
    """解析模板归属工作区：显式指定优先（不存在 404），否则按所属表反推，皆无落 None."""
    if workspace_id is not None:
        from cndb.plugins.workspaces.models import Workspace

        if db.get(Workspace, workspace_id) is None:
            raise HTTPException(status_code=404, detail=f"工作区不存在 id={workspace_id}")
        return workspace_id
    if table_id is not None:
        from cndb.plugins.tables.models import DataTable

        table = db.get(DataTable, table_id)
        if table is not None:
            return table.workspace_id
    return None


def _resolve_extra_tables(db: Session, extra_table_ids: list[int]) -> list[int]:
    """校验额外引用表 id 列表（去重保序），任一不存在则 404；渲染时的 READ 权限在渲染端校验."""
    from cndb.plugins.tables.models import DataTable

    resolved: list[int] = []
    for tid in dict.fromkeys(extra_table_ids):
        if not db.get(DataTable, tid):
            raise HTTPException(status_code=404, detail=f"额外引用表不存在 id={tid}")
        resolved.append(tid)
    return resolved


def _resolve_view(db: Session, table_id: int | None, view_id: int, user: User) -> Any:
    """校验视图可绑定性：存在、归属指定主表、对当前用户可见；返回 DataView.

    Args:
        db: 数据库会话
        table_id: 模板绑定的主表 ID（None 时视为未绑定主表，直接 400）
        view_id: 目标视图 ID
        user: 当前用户

    Raises:
        HTTPException(400): 未绑定主表、视图不存在或视图不属于该主表
        HTTPException(403): 他人个人视图不可见
    """
    from cndb.plugins.tables.models import DataView

    if table_id is None:
        raise HTTPException(status_code=400, detail="绑定视图前须先关联数据表")
    dv = db.get(DataView, view_id)
    if dv is None or dv.table_id != table_id:
        raise HTTPException(status_code=400, detail=f"视图不存在或不属于该数据表 view_id={view_id}")
    # 可见性与视图路由一致：公共视图 + 本人个人视图；他人个人视图不可见
    if dv.owner_id is not None and dv.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该视图")
    return dv


@router.post("", response_model=TemplateResponse, status_code=201)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    _validate_format(payload.output_format)
    _validate_theme(payload.theme)
    # 权限前置：用户必须对目标表有 READ 权限才能创建报表模板
    if payload.table_id is not None:
        _authorize_table_for_template(db, payload.table_id, current_user, TableAction.READ)
    workspace_id = _resolve_workspace_id(db, payload.workspace_id, payload.table_id)
    extra_ids = _resolve_extra_tables(db, payload.extra_table_ids)
    # 额外引用表也需要 READ 权限（防止借模板越权读跨工作区表数据）
    for etid in extra_ids:
        _authorize_table_for_template(db, etid, current_user, TableAction.READ)
    if payload.view_id is not None:
        _resolve_view(db, payload.table_id, payload.view_id, current_user)
    try:
        _jinja_env.from_string(payload.template_content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模板语法错误: {exc}") from exc
    tpl = ReportTemplate(
        table_id=payload.table_id,
        view_id=payload.view_id,
        workspace_id=workspace_id,
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
    current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    _authorize_template_access(db, tpl, current_user, TableAction.READ)
    return tpl


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportTemplate:
    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    # 首先验证用户对模板当前归属有 READ 权限（能读才能更新）
    _authorize_template_access(db, tpl, current_user, TableAction.READ)
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
    # 修改 table_id 时：用户必须对新表有 READ 权限
    if "table_id" in ud:
        new_table_id = ud["table_id"]
        if new_table_id is not None and new_table_id != tpl.table_id:
            _authorize_table_for_template(db, new_table_id, current_user, TableAction.READ)
    if "extra_table_ids" in ud and ud["extra_table_ids"] is not None:
        extra_ids = _resolve_extra_tables(db, ud["extra_table_ids"])
        for etid in extra_ids:
            _authorize_table_for_template(db, etid, current_user, TableAction.READ)
        ud["extra_table_ids"] = extra_ids
    # 修改 view_id 时：视图必须归属于生效主表（本次请求传入的新主表优先，否则沿用模板现主表）且对用户可见
    if "view_id" in ud and ud["view_id"] is not None:
        effective_table_id = ud.get("table_id") if ud.get("table_id") is not None else tpl.table_id
        _resolve_view(db, effective_table_id, ud["view_id"], current_user)
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
    current_user: User = Depends(get_current_user),
) -> None:
    tpl = db.get(ReportTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    _authorize_template_access(db, tpl, current_user, TableAction.READ)
    db.delete(tpl)
    db.commit()


_CONTENT_TYPES: dict[str, str] = {
    OutputFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    OutputFormat.PDF: "application/pdf",
    OutputFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    OutputFormat.HTML: "text/html; charset=utf-8",
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

    # 参数取值校验：声明了 options 的参数，传入值必须在可选列表内
    for p in tpl.parameters or []:
        opts = p.get("options") or []
        if opts and p.get("name") in payload.params and payload.params[p["name"]] not in ([None, "", *opts]):
            raise HTTPException(
                status_code=400,
                detail=f"参数 {p['name']} 取值无效，可选值：{'/'.join(opts)}",
            )

    # 解析有效视图：请求临时指定优先，其次模板持久化绑定；视图校验失败 400/403
    effective_view_id = payload.view_id if payload.view_id is not None else tpl.view_id
    view = (
        _resolve_view(db, payload.table_id, effective_view_id, _current_user) if effective_view_id is not None else None
    )

    # 加载主表（带 READ 权限校验 + 字段隐藏；绑定视图时按视图 filters/sortings 取数）
    table, records = _load_table_records(db, payload.table_id, _current_user, view=view)

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
        "view_name": view.name if view is not None else None,
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


__all__ = [
    "RENDER_TIMEOUT",
    "_add_rich_runs",
    "_cjk_font_candidates",
    "_coerce_numeric",
    "_ensure_pdf_font",
    "_flatten_for_report",
    "_group_stats",
    "_html_escape",
    "_html_rich_text",
    "_is_cjk_family",
    "_jinja_env",
    "_load_table_records",
    "_make_pdf_table",
    "_pdf_escape",
    "_pdf_font_state",
    "_pdf_markdown_to_rml",
    "_pdf_table_style_cmds",
    "_render_docx",
    "_render_html",
    "_render_pdf",
    "_render_with_timeout",
    "_render_xlsx",
    "_run_command",
    "_stats",
    "cndb_report_header",
    "router",
]

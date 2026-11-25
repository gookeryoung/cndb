"""analytics 求值路由：公式校验与按公式计算派生指标.

端点（前缀 /{workspace_id}/analytics）：
- POST "/validate"  校验公式语法 + 字段引用（无需落库，供编辑器实时反馈）
- POST "/compute"   按公式计算派生列，返回行数据 + 描述统计
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.analytics import services
from cndb.plugins.analytics.schemas import (
    ComputeRequest,
    ComputeResponse,
    FormulaCheck,
    ValidateRequest,
    ValidateResponse,
)
from cndb.plugins.analytics.services.formula import FormulaError, parse, referenced_fields
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_workspace_permission,
    get_table_or_404,
)
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/analytics", tags=["analytics"])


def _table_for_read(workspace_id: int, table_id: int, user: User, db: Session) -> DataTable:
    """取表并校验可读（工作区成员 / 表级 READ 权限）."""
    return get_table_or_404(table_id, workspace_id, db, user=user, action=TableAction.READ)


def _resolve_compute_source(
    workspace_id: int,
    payload: ComputeRequest,
    user: User,
    db: Session,
) -> tuple[DataTable, list[dict[str, Any]] | None, str, set[str] | None]:
    """解析求值数据源（ADR 0158 D1/D4）：返回 (表, 附加筛选, 逻辑, 允许字段集合).

    - `source.type=table` / 兼容字段 `table_id`：现状不变（允许字段 = None，交由 compute 判定）；
    - `source.type=link`：**每次**都过 `resolve_link`（失效 404 / 无读权 403），
      并把链接视图筛选并入扫描范围；允许字段 = 链接可见字段（已裁剪隐藏字段）。
    """
    source = payload.source
    if source is None or source.type == "table":
        table_id = source.id if source is not None else payload.table_id
        if table_id is None:  # pragma: no cover - schema 已校验
            raise HTTPException(status_code=400, detail="请指定数据源")
        return _table_for_read(workspace_id, table_id, user, db), None, payload.filter_logic.upper(), None

    from cndb.plugins.workspaces.services.links import link_fields, link_query, resolve_link

    if source.link_id is None:  # pragma: no cover - schema 已校验
        raise HTTPException(status_code=400, detail="source.type=link 时必须给 link_id")
    resolved = resolve_link(db, user, workspace_id=workspace_id, link_id=source.link_id)
    view_filters, _view_sorts, view_logic = link_query(resolved)
    extra_filters = list(view_filters or []) + list(payload.filters or [])
    logic = payload.filter_logic.upper() if payload.filters else view_logic
    allowed = {field["name"] for field in link_fields(db, user, resolved)}
    return resolved.table, (extra_filters or None), logic, allowed


def _run_compute_rows(
    payload: ComputeRequest,
    formulas: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    field_names: list[str],
    total: int,
    truncated: bool,
) -> dict[str, Any]:
    """复合数据源的统一计算入口：字段白名单校验 + 复用 `compute_rows`."""
    _check_allowed_fields(payload, set(field_names))
    try:
        return services.compute.compute_rows(
            rows,
            field_names,
            total=total,
            truncated=truncated,
            formulas=formulas,
            fields=payload.fields,
            limit=payload.limit,
            summary=payload.summary,
        )
    except FormulaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _check_allowed_fields(payload: ComputeRequest, allowed_fields: set[str]) -> None:
    """链接 / 汇总数据源：公式、返回字段、窗口分区排序字段必须都在可见字段内（H58 / ADR 0159 C3）."""
    referenced: set[str] = set(payload.fields or [])
    for spec in payload.formulas:
        try:
            referenced |= set(referenced_fields(parse(spec.expr)))
        except FormulaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for ctx in (spec.partition_by, spec.order_by):
            if ctx:
                referenced.add(ctx)
    unknown = sorted(f for f in referenced if f not in allowed_fields)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"字段不可用于该数据源（不存在或被隐藏）: {', '.join(unknown)}",
        )


@router.post("/validate", response_model=ValidateResponse)
def validate_formulas(
    workspace_id: int,
    payload: ValidateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ValidateResponse:
    """校验公式：语法白名单 + 字段引用（给了 source / table_id 才做字段检查）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    field_names: list[str] | None = None
    if payload.source is not None:
        # 复合数据源（ADR 0159 P2）：字段白名单 = 合成后的字段清单（逐输入同权，L1/L2）
        table_id = payload.source.id if payload.source.type == "table" else payload.table_id
        if table_id is not None and payload.source.type == "table":
            _table_for_read(workspace_id, table_id, current_user, db)
        field_names = services.templates.source_field_names(db, current_user, workspace_id, payload.source, table_id)
    elif payload.table_id is not None:
        _table_for_read(workspace_id, payload.table_id, current_user, db)
        field_names = services.templates.table_field_names(db, workspace_id, payload.table_id)
    known = set(field_names) if field_names is not None else None

    results: list[FormulaCheck] = []
    all_ok = True
    for spec in payload.formulas:
        try:
            node = parse(spec.expr)
        except FormulaError as exc:
            all_ok = False
            results.append(FormulaCheck(key=spec.key, expr=spec.expr, ok=False, error=str(exc)))
            continue
        fields = sorted(referenced_fields(node))
        unknown = sorted(f for f in fields if known is not None and f not in known)
        if unknown:
            all_ok = False
            results.append(
                FormulaCheck(
                    key=spec.key,
                    expr=spec.expr,
                    ok=False,
                    error=f"引用了不存在的字段: {', '.join(unknown)}",
                    fields=fields,
                )
            )
            continue
        results.append(FormulaCheck(key=spec.key, expr=spec.expr, ok=True, fields=fields))

    return ValidateResponse(ok=all_ok, results=results, table_fields=field_names or [])


@router.post("/compute", response_model=ComputeResponse)
def compute(
    workspace_id: int,
    payload: ComputeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """按公式计算派生指标列并返回描述统计（数据源可为本表 / 链接 / 汇总，ADR 0158/0159）."""
    formulas = [
        {
            "key": s.key,
            "label": s.label or s.key,
            "expr": s.expr,
            "partition_by": s.partition_by,
            "order_by": s.order_by,
            "order_desc": s.order_desc,
        }
        for s in payload.formulas
    ]
    keys = [s["key"] for s in formulas]
    if len(set(keys)) != len(keys):
        raise HTTPException(status_code=400, detail="公式键重复")

    # 复合数据源（ADR 0159 P1）：跨工作区关联，先合成行集再走同一套计算
    if payload.source is not None and payload.source.type == "join":
        from cndb.plugins.analytics.services import join_source

        rows, field_names, total, truncated = join_source.join_rows(db, current_user, workspace_id, payload.source)
        return _run_compute_rows(payload, formulas, rows, field_names, total, truncated)

    # 复合数据源（ADR 0159 P0）：先合成行集，再走同一套计算
    if payload.source is not None and payload.source.type == "union":
        from cndb.plugins.analytics.services import union_source

        rows, field_names, total, truncated = union_source.union_rows(db, current_user, workspace_id, payload.source)
        _check_allowed_fields(payload, set(field_names))
        try:
            return services.compute.compute_rows(
                rows,
                field_names,
                total=total,
                truncated=truncated,
                formulas=formulas,
                fields=payload.fields,
                limit=payload.limit,
                summary=payload.summary,
            )
        except FormulaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    table, extra_filters, filter_logic, allowed_fields = _resolve_compute_source(
        workspace_id, payload, current_user, db
    )
    if allowed_fields is not None:
        _check_allowed_fields(payload, allowed_fields)
    try:
        return services.compute.compute(
            db,
            table,
            current_user,
            formulas=formulas,
            fields=payload.fields,
            limit=payload.limit,
            summary=payload.summary,
            filters=extra_filters if extra_filters is not None else payload.filters,
            filter_logic=filter_logic,
        )
    except FormulaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["router"]

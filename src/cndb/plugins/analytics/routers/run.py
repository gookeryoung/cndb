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


@router.post("/validate", response_model=ValidateResponse)
def validate_formulas(
    workspace_id: int,
    payload: ValidateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ValidateResponse:
    """校验公式：语法白名单 + 字段引用（给了 table_id 才做字段检查）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    field_names: list[str] | None = None
    if payload.table_id is not None:
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
    """按公式计算派生指标列并返回描述统计."""
    table = _table_for_read(workspace_id, payload.table_id, current_user, db)
    formulas = [{"key": s.key, "label": s.label or s.key, "expr": s.expr} for s in payload.formulas]
    keys = [s["key"] for s in formulas]
    if len(set(keys)) != len(keys):
        raise HTTPException(status_code=400, detail="公式键重复")
    try:
        return services.compute.compute(
            db,
            table,
            current_user,
            formulas=formulas,
            fields=payload.fields,
            limit=payload.limit,
            summary=payload.summary,
        )
    except FormulaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["router"]

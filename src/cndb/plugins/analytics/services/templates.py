"""分析模板持久化：配置归一化（含公式校验）与 CRUD 辅助."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.models import AnalyticsTemplate
from cndb.plugins.analytics.schemas import TemplateConfig
from cndb.plugins.analytics.services.formula import FormulaError, parse, referenced_fields
from cndb.plugins.tables.models import DataTable


def table_field_names(db: Session, workspace_id: int, table_id: int | None) -> list[str] | None:
    """取表（须属于该工作区）的可见字段名；未指定表时返回 None.

    Raises:
        HTTPException(404): 表不存在或不属于该工作区.
    """
    if table_id is None:
        return None
    dt = db.query(DataTable).filter(DataTable.id == table_id, DataTable.workspace_id == workspace_id).first()
    if dt is None:
        raise HTTPException(status_code=404, detail="表不存在")
    return [f.name for f in dt.active_fields()]


def normalize_config(
    config: TemplateConfig,
    field_names: list[str] | None,
) -> dict[str, Any]:
    """校验并归一化模板配置（公式语法 + 字段引用），返回可入库的 dict.

    Raises:
        HTTPException(400): 公式非法 / 键重复 / 引用未知字段.
    """
    keys: set[str] = set()
    formulas: list[dict[str, Any]] = []
    for spec in config.formulas:
        if spec.key in keys:
            raise HTTPException(status_code=400, detail=f"公式键重复: {spec.key}")
        keys.add(spec.key)
        try:
            node = parse(spec.expr)
        except FormulaError as exc:
            raise HTTPException(status_code=400, detail=f"公式 {spec.key} 非法: {exc}") from exc
        fields = referenced_fields(node)
        if field_names is not None:
            unknown = sorted(f for f in fields if f not in field_names)
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=f"公式 {spec.key} 引用了不存在的字段: {', '.join(unknown)}",
                )
        formulas.append({"key": spec.key, "label": spec.label or spec.key, "expr": spec.expr})

    chart: dict[str, Any] | None = None
    if config.chart is not None:
        refs = [config.chart.x, config.chart.y, config.chart.series]
        if field_names is not None:
            allowed = set(field_names) | keys
            unknown = sorted({r for r in refs if r and r not in allowed})
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=f"图表引用了不存在的字段: {', '.join(unknown)}",
                )
        chart = config.chart.model_dump()

    return {
        "formulas": formulas,
        "chart": chart,
        "fields": list(config.fields),
        "limit": config.limit,
    }


def get_template(db: Session, workspace_id: int, template_id: int) -> AnalyticsTemplate:
    """取模板（须属于该工作区）.

    Raises:
        HTTPException(404): 模板不存在.
    """
    tpl = (
        db.query(AnalyticsTemplate)
        .filter(AnalyticsTemplate.id == template_id, AnalyticsTemplate.workspace_id == workspace_id)
        .first()
    )
    if tpl is None:
        raise HTTPException(status_code=404, detail="分析模板不存在")
    return tpl


def create_template(
    db: Session,
    user: User,
    *,
    workspace_id: int,
    name: str,
    description: str,
    table_id: int | None,
    config: TemplateConfig,
) -> AnalyticsTemplate:
    """新建模板（落库前校验公式与字段引用）."""
    normalized = normalize_config(config, table_field_names(db, workspace_id, table_id))
    tpl = AnalyticsTemplate(
        workspace_id=workspace_id,
        table_id=table_id,
        name=name,
        description=description,
        config=normalized,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def update_template(
    db: Session,
    user: User,
    tpl: AnalyticsTemplate,
    *,
    name: str | None = None,
    description: str | None = None,
    table_id: int | None = None,
    config: TemplateConfig | None = None,
) -> AnalyticsTemplate:
    """更新模板（仅传入的字段生效）."""
    if name is not None:
        tpl.name = name
    if description is not None:
        tpl.description = description
    if table_id is not None:
        tpl.table_id = table_id
    if config is not None:
        tpl.config = normalize_config(config, table_field_names(db, tpl.workspace_id, tpl.table_id))
    tpl.updated_by_id = user.id
    db.commit()
    db.refresh(tpl)
    return tpl


def delete_template(db: Session, tpl: AnalyticsTemplate) -> None:
    """删除模板."""
    db.delete(tpl)
    db.commit()


__all__ = [
    "create_template",
    "delete_template",
    "get_template",
    "normalize_config",
    "table_field_names",
    "update_template",
]

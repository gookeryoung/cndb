"""分析模板持久化：配置归一化（含公式校验）与 CRUD 辅助."""

from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.models import AnalyticsTemplate
from cndb.plugins.analytics.schemas import TemplateConfig
from cndb.plugins.analytics.services.compute import AGG_ORDER, metric_key
from cndb.plugins.analytics.services.formula import FormulaError, parse, referenced_fields
from cndb.plugins.tables.models import DataTable


def link_field_names(
    db: Session,
    user: Any,
    workspace_id: int,
    link_id: int | None,
) -> list[str] | None:
    """链接数据源的可见字段名（ADR 0158 C3）：过 `resolve_link` 后按隐藏字段裁剪.

    链接无效 → 404；对源工作区无读权 → 403（与只读网格同权，不静默降级）。
    """
    from cndb.plugins.workspaces.services.links import link_fields, resolve_link

    if link_id is None:
        return None
    resolved = resolve_link(db, user, workspace_id=workspace_id, link_id=link_id)
    return [field["name"] for field in link_fields(db, user, resolved)]


def source_field_names(
    db: Session,
    user: Any,
    workspace_id: int,
    source: Any,
    table_id: int | None,
) -> list[str] | None:
    """按模板数据源取字段白名单（链接优先，否则退回本表）."""
    if source is not None and getattr(source, "type", "table") == "link":
        return link_field_names(db, user, workspace_id, getattr(source, "link_id", None))
    return table_field_names(db, workspace_id, table_id)


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
    source = getattr(config, "source", None)
    source_payload: dict[str, Any] | None = None
    if source is not None:
        source_payload = {"type": source.type}
        if source.type == "link":
            source_payload["link_id"] = source.link_id
        elif source.id is not None:
            source_payload["id"] = source.id
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
        entry: dict[str, Any] = {"key": spec.key, "label": spec.label or spec.key, "expr": spec.expr}
        for role_field, label in ((spec.partition_by, "分区字段"), (spec.order_by, "排序字段")):
            if not role_field:
                continue
            if field_names is not None and role_field not in field_names:
                raise HTTPException(
                    status_code=400,
                    detail=f"公式 {spec.key} 的{label}不存在: {role_field}",
                )
            entry["partition_by" if label == "分区字段" else "order_by"] = role_field
        if spec.order_desc:
            entry["order_desc"] = True
        formulas.append(entry)

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
        if config.chart.aggregation not in AGG_ORDER:
            raise HTTPException(
                status_code=400,
                detail=f"图表聚合方式非法: {config.chart.aggregation}（可选 {', '.join(AGG_ORDER)}）",
            )
        chart = config.chart.model_dump()

    summary: dict[str, Any] | None = None
    if config.summary is not None:
        spec = config.summary
        if not spec.metrics:
            raise HTTPException(status_code=400, detail="分组汇总至少需要一个指标")
        bad_aggs = sorted({m.agg for m in spec.metrics if m.agg not in AGG_ORDER})
        if bad_aggs:
            raise HTTPException(
                status_code=400,
                detail=f"分组汇总聚合方式非法: {', '.join(bad_aggs)}（可选 {', '.join(AGG_ORDER)}）",
            )
        if spec.sort_order not in ("asc", "desc"):
            raise HTTPException(status_code=400, detail=f"分组汇总排序方向非法: {spec.sort_order}")
        allowed = set(field_names or []) | keys
        if field_names is not None and spec.group_by and spec.group_by not in field_names:
            raise HTTPException(status_code=400, detail=f"分组字段不存在: {spec.group_by}")
        unknown = sorted({m.field for m in spec.metrics if field_names is not None and m.field not in allowed})
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"分组汇总指标引用了不存在的字段或公式: {', '.join(unknown)}",
            )
        metric_keys = {metric_key(m.agg, m.field) for m in spec.metrics}
        if spec.sort_by and spec.sort_by not in metric_keys and spec.sort_by not in allowed:
            raise HTTPException(status_code=400, detail=f"分组汇总排序指标不存在: {spec.sort_by}")
        summary = spec.model_dump()

    result: dict[str, Any] = {
        "formulas": formulas,
        "chart": chart,
        "summary": summary,
        "fields": list(config.fields),
        "limit": config.limit,
    }
    if source_payload is not None:
        result["source"] = source_payload
    return result


def config_source_payload(config: dict[str, Any] | None) -> dict[str, Any]:
    """模板配置里的数据源（ADR 0158 D2）：缺省解释为「本工作区的 table 源」."""
    source = (config or {}).get("source")
    return source if isinstance(source, dict) else {"type": "table"}


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
    """新建模板（落库前校验公式与字段引用）.

    数据源支持「本表 / 链接」（ADR 0158 P1）：链接源在保存期即校验可读（404/403），
    字段白名单取链接可见字段；`table_id` 仍落源表 id，供旧消费方展示。
    """
    fields = source_field_names(db, user, workspace_id, getattr(config, "source", None), table_id)
    source = getattr(config, "source", None)
    if source is not None and getattr(source, "type", "table") == "link":
        from cndb.plugins.workspaces.services.links import resolve_link

        table_id = resolve_link(db, user, workspace_id=workspace_id, link_id=source.link_id).table.id
    normalized = normalize_config(config, fields)
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
        source = getattr(config, "source", None)
        fields = source_field_names(db, user, tpl.workspace_id, source, tpl.table_id)
        if source is not None and getattr(source, "type", "table") == "link":
            from cndb.plugins.workspaces.services.links import resolve_link

            tpl.table_id = resolve_link(db, user, workspace_id=tpl.workspace_id, link_id=source.link_id).table.id
        tpl.config = normalize_config(config, fields)
    tpl.updated_by_id = user.id
    db.commit()
    db.refresh(tpl)
    return tpl


def delete_template(db: Session, tpl: AnalyticsTemplate) -> None:
    """删除模板."""
    db.delete(tpl)
    db.commit()


def _fit_name(name: str, limit: int = 200) -> str:
    """按模型列宽截断名称（超长时宁可截断也不让复制失败）."""
    return name if len(name) <= limit else name[:limit]


def _name_with_suffix(source_name: str, suffix: str, limit: int = 200) -> str:
    """给副本名追加后缀；超长时先截断原名、保留完整后缀（避免截断后重名死循环）."""
    room = max(0, limit - len(suffix))
    return _fit_name(f"{source_name[:room]}{suffix}", limit)


def duplicate_name(db: Session, workspace_id: int, source_name: str) -> str:
    """生成不重名的副本名称：「{原名} 副本」，重名时追加 " (2)"、" (3)"…"""
    existing = {
        row[0] for row in db.query(AnalyticsTemplate.name).filter(AnalyticsTemplate.workspace_id == workspace_id).all()
    }
    base = _name_with_suffix(source_name, " 副本")
    if base not in existing:
        return base
    index = 2
    while True:
        candidate = _name_with_suffix(source_name, f" 副本 ({index})")
        if candidate not in existing:
            return candidate
        index += 1


def duplicate_template(
    db: Session,
    user: User,
    tpl: AnalyticsTemplate,
    *,
    name: str | None = None,
) -> AnalyticsTemplate:
    """复制模板：复制 config / table_id / description，创建人改为当前用户.

    Args:
        name: 显式指定副本名称；空则自动生成不重名的「原名 副本」.
    """
    target_name = name.strip() if name and name.strip() else duplicate_name(db, tpl.workspace_id, tpl.name)
    copy_tpl = AnalyticsTemplate(
        workspace_id=tpl.workspace_id,
        table_id=tpl.table_id,
        name=target_name,
        description=tpl.description,
        # 深拷贝，避免两个模板共享同一个 config 对象
        config=copy.deepcopy(tpl.config or {}),
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(copy_tpl)
    db.commit()
    db.refresh(copy_tpl)
    return copy_tpl


__all__ = [
    "create_template",
    "delete_template",
    "duplicate_name",
    "duplicate_template",
    "get_template",
    "normalize_config",
    "table_field_names",
    "update_template",
]

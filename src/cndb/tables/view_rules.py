"""视图规则校验：筛选/排序/字段选项的结构校验与归一化.

DataView.save() 强制走本模块，保证入库的规则结构合法、字段引用存在、
过滤值可编译；排序与过滤值合法性通过查询编译 dry-run 预检。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cndb.tables import query
from cndb.tables.models import DataTable, DataView

# 字段选项：hidden 显隐 / width 列宽 / order 展示顺序
_FIELD_OPTION_DEFAULTS = {"hidden": False, "width": 200, "order": 0}
_WIDTH_RANGE = (40, 800)


class InvalidViewError(Exception):
    """视图规则非法（结构/字段引用/过滤值不合法）."""


@dataclass
class ViewRules:
    """视图规则集合：待校验归一化的原始输入（None 表示空规则）."""

    view_type: str = DataView.ViewType.GRID
    filter_type: str = DataView.FilterType.AND
    filters: Any = field(default_factory=list)
    sortings: Any = field(default_factory=list)
    field_options: Any = field(default_factory=dict)


def normalize_filters(table: DataTable, filters: Any, filter_type: str) -> list[dict[str, Any]]:
    """校验筛选规则结构并归一化为 [{"field","op","value"}]."""
    if not isinstance(filters, list):
        raise InvalidViewError("filters 必须是数组")
    normalized: list[dict[str, Any]] = []
    for rule in filters:
        if not isinstance(rule, Mapping):
            raise InvalidViewError("每条筛选规则必须是对象")
        field_name, op = rule.get("field"), rule.get("op")
        if not isinstance(field_name, str) or not field_name:
            raise InvalidViewError("筛选规则缺少字段名")
        if op not in query.FILTER_OPS:
            raise InvalidViewError(f"不支持的过滤操作符: {op}")
        normalized.append({"field": field_name, "op": op, "value": rule.get("value")})
    # dry-run 编译：保存时即发现坏字段引用与坏值，避免运行期才报错
    try:
        query.compile_filters(table, normalized, filter_type)
    except query.InvalidQueryError as exc:
        raise InvalidViewError(str(exc)) from exc
    return normalized


def _normalize_sortings(table: DataTable, sortings: Any) -> list[dict[str, Any]]:
    """校验排序规则结构并归一化为 [{"field","desc"}]."""
    if not isinstance(sortings, list):
        raise InvalidViewError("sortings 必须是数组")
    normalized: list[dict[str, Any]] = []
    for rule in sortings:
        if not isinstance(rule, Mapping):
            raise InvalidViewError("每条排序规则必须是对象")
        field_name = rule.get("field")
        if not isinstance(field_name, str) or not field_name:
            raise InvalidViewError("排序规则缺少字段名")
        normalized.append({"field": field_name, "desc": bool(rule.get("desc"))})
    try:
        query.compile_sortings(table, normalized)
    except query.InvalidQueryError as exc:
        raise InvalidViewError(str(exc)) from exc
    return normalized


def _normalize_field_options(table: DataTable, field_options: Any) -> dict[str, dict[str, Any]]:
    """校验字段选项并归一化：补全 hidden/width/order 默认值，未知键拒绝."""
    if not isinstance(field_options, dict):
        raise InvalidViewError("field_options 必须是对象")
    known = {str(field.name) for field in table.active_fields()}
    normalized: dict[str, dict[str, Any]] = {}
    for name, options in field_options.items():
        if name not in known:
            raise InvalidViewError(f"字段选项引用了未知字段: {name}")
        if not isinstance(options, Mapping):
            raise InvalidViewError(f"字段 {name} 的选项必须是对象")
        item = dict(_FIELD_OPTION_DEFAULTS)
        hidden = options.get("hidden", item["hidden"])
        width = options.get("width", item["width"])
        order = options.get("order", item["order"])
        if not isinstance(hidden, bool):
            raise InvalidViewError(f"字段 {name} 的 hidden 必须是布尔值")
        if not isinstance(width, int) or isinstance(width, bool) or not _WIDTH_RANGE[0] <= width <= _WIDTH_RANGE[1]:
            raise InvalidViewError(f"字段 {name} 的 width 必须是 {_WIDTH_RANGE[0]} 到 {_WIDTH_RANGE[1]} 的整数")
        if not isinstance(order, int) or isinstance(order, bool):
            raise InvalidViewError(f"字段 {name} 的 order 必须是整数")
        item.update({"hidden": hidden, "width": width, "order": order})
        normalized[name] = item
    return normalized


def normalize_view(table: DataTable, rules: ViewRules) -> dict[str, Any]:
    """校验并归一化视图规则集合，非法抛 InvalidViewError，返回可入库的三个规则字段."""
    if rules.view_type not in {choice.value for choice in DataView.ViewType}:
        raise InvalidViewError(f"未知视图形态: {rules.view_type}")
    if rules.filter_type not in query.MATCH_TYPES:
        raise InvalidViewError(f"不支持的条件组合方式: {rules.filter_type}")
    return {
        "filters": normalize_filters(table, rules.filters, rules.filter_type),
        "sortings": _normalize_sortings(table, rules.sortings),
        "field_options": _normalize_field_options(table, rules.field_options),
    }

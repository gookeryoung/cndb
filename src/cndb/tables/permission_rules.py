"""表级权限规则校验：角色覆盖、字段隐藏与行级过滤的结构归一化.

结构与视图规则同风格：dataclass 封装输入、normalize 入口校验并归一化；
行级过滤复用 view_rules 的筛选校验（同 op/值语义），字段隐藏校验角色合法.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cndb.tables.models import DataTable
from cndb.tables.query import MATCH_TYPES
from cndb.tables.view_rules import InvalidViewError, normalize_filters

# 合法工作区角色（与 WorkspaceMember.Role 取值一致）
_VALID_ROLES = frozenset({"owner", "admin", "editor", "commenter", "viewer"})


class InvalidPermissionError(Exception):
    """表级权限规则非法."""


@dataclass
class PermissionRules:
    """表级权限规则输入：空角色表示不覆盖（回落工作区默认）."""

    read_role: str = ""
    edit_records_role: str = ""
    edit_views_role: str = ""
    edit_schema_role: str = ""
    hidden_fields: Any = field(default_factory=dict)
    row_filters: Any = field(default_factory=list)
    row_filter_type: str = "AND"


def _normalize_role(name: str, role: Any) -> str:
    """校验单个角色覆盖值：空串表示不覆盖，否则必须是合法角色."""
    if role is None:
        return ""
    if not isinstance(role, str):
        raise InvalidPermissionError(f"{name} 必须是字符串")
    if role == "":
        return ""
    if role not in _VALID_ROLES:
        raise InvalidPermissionError(f"{name} 不是合法角色: {role}")
    return role


def _normalize_hidden_fields(table: DataTable, hidden_fields: Any) -> dict[str, str]:
    """校验字段级隐藏结构 {字段名: 最低可见角色}，未知字段与非法角色拒绝."""
    if not isinstance(hidden_fields, dict):
        raise InvalidPermissionError("hidden_fields 必须是对象")
    known = {str(item.name) for item in table.active_fields()}
    normalized: dict[str, str] = {}
    for field_name, role in hidden_fields.items():
        if field_name not in known:
            raise InvalidPermissionError(f"字段隐藏引用了未知字段: {field_name}")
        if not isinstance(role, str) or role not in _VALID_ROLES:
            raise InvalidPermissionError(f"字段 {field_name} 的隐藏角色必须是合法角色")
        normalized[field_name] = role
    return normalized


def normalize_permission(table: DataTable, rules: PermissionRules) -> dict[str, Any]:
    """校验并归一化表级权限规则，非法抛 InvalidPermissionError."""
    try:
        row_filters = normalize_filters(table, rules.row_filters, rules.row_filter_type)
    except InvalidViewError as exc:
        raise InvalidPermissionError(f"行级过滤规则非法: {exc}") from exc
    if rules.row_filter_type not in MATCH_TYPES:
        raise InvalidPermissionError(f"不支持的条件组合方式: {rules.row_filter_type}")
    return {
        "read_role": _normalize_role("read_role", rules.read_role),
        "edit_records_role": _normalize_role("edit_records_role", rules.edit_records_role),
        "edit_views_role": _normalize_role("edit_views_role", rules.edit_views_role),
        "edit_schema_role": _normalize_role("edit_schema_role", rules.edit_schema_role),
        "hidden_fields": _normalize_hidden_fields(table, rules.hidden_fields),
        "row_filters": row_filters,
        "row_filter_type": rules.row_filter_type if row_filters else "AND",
    }

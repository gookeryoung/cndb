"""表单字段配置：保存时校验 + 运行时解析.

保存校验：field_name 必须存在于目标表、不得重复、不得为空——错误以中文明细列表返回。
运行时解析：过滤已软删（trashed）与表级隐藏（TablePermission.hidden_fields）字段，
并返回失效字段清单，供 meta 响应提示（不 500、不泄露隐藏字段）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.forms.schemas.models import ALLOWED_FORM_WIDGETS, FORM_WIDGET_FIELD_TYPES
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.access import get_hidden_field_names


def validate_field_config(
    db: Session,
    table_id: int,
    field_config: list[dict[str, Any]],
) -> list[str]:
    """校验表单字段配置，返回错误明细列表（空列表 = 通过）.

    规则：
    - 每项必须含非空 field_name
    - field_name 必须在目标表存在（含已软删字段——保存时允许，运行时再过滤，
      避免字段暂时进回收站导致表单无法保存）
    - field_name 不得重复
    - widget（控件覆盖）必须在 ALLOWED_FORM_WIDGETS 内、与字段类型兼容
      （FORM_WIDGET_FIELD_TYPES 矩阵），select/radio 须带非空 options
    """
    errors: list[str] = []
    fields = db.query(DataField).filter(DataField.table_id == table_id).all()
    valid_names = {f.name for f in fields}
    type_by_name = {f.name: (f.field_type or "") for f in fields}
    seen: set[str] = set()
    for i, item in enumerate(field_config):
        name = item.get("field_name") if isinstance(item, dict) else None
        if not name or not str(name).strip():
            errors.append(f"field_config[{i}].field_name 不能为空")
            continue
        name = str(name)
        if name not in valid_names:
            errors.append(f"field_config[{i}] 字段 '{name}' 不存在于目标表")
        if name in seen:
            errors.append(f"field_config[{i}] 字段 '{name}' 重复")
        seen.add(name)
        errors.extend(_validate_widget(i, name, item, type_by_name.get(name, "")))
    return errors


def _validate_widget(
    index: int,
    name: str,
    item: dict[str, Any],
    field_type: str,
) -> list[str]:
    """校验单条配置的控件覆盖规则，返回错误明细."""
    widget = item.get("widget")
    if not widget:
        return []
    prefix = f"field_config[{index}] 字段 '{name}'"
    if widget not in ALLOWED_FORM_WIDGETS:
        return [f"{prefix} 的控件覆盖非法: {widget}，合法值 {list(ALLOWED_FORM_WIDGETS)}"]
    errors: list[str] = []
    compat = FORM_WIDGET_FIELD_TYPES.get(widget, set())
    if field_type and field_type not in compat:
        errors.append(f"{prefix}（类型 {field_type}）不支持控件覆盖 '{widget}'")
    if widget in ("select", "radio"):
        options = (item.get("widget_config") or {}).get("options")
        if not isinstance(options, list) or not options:
            errors.append(f"{prefix} 的控件 '{widget}' 需要 widget_config.options 非空列表")
        elif not all(isinstance(o, (str, dict)) for o in options):
            errors.append(f"{prefix} 的 options 每项须为字符串或 {{value,label}} 对象")
    return errors


def resolve_form_fields(
    db: Session,
    form: Any,
    table: DataTable,
    user: User,
) -> tuple[list[dict[str, Any]], list[str]]:
    """运行时解析表单字段配置.

    Returns:
        (fields, invalid_fields):
        - fields: 过滤软删与当前用户不可见（表级隐藏）字段后的配置列表；
          配置为空时回退为表的全部活跃字段（表单镜像整表）。
          每项附带 field_type / field_required / config（来自字段定义），
          供前端选择控件与判定必填
        - invalid_fields: 配置引用但当前失效（软删/隐藏）的字段名
    """
    hidden = get_hidden_field_names(db, table, user)
    fields_by_name = {f.name: f for f in table.fields}

    def _enrich(item: dict[str, Any], field: DataField) -> dict[str, Any]:
        enriched = dict(item)
        enriched.setdefault("field_type", field.field_type)
        enriched.setdefault("config", field.config or {})
        # required=null 表示跟随字段定义，此处解析为具体布尔值
        if enriched.get("required") is None:
            enriched["required"] = bool(field.required)
        return enriched

    config: list[dict[str, Any]] = list(form.field_config or [])
    if not config:
        # 空配置 → 表单镜像整表（不含软删字段）
        return (
            [
                _enrich(
                    {"field_name": f.name, "label": f.name, "editable": True, "visible": True},
                    f,
                )
                for f in table.active_fields()
            ],
            sorted(n for n in hidden if any(f.name == n for f in table.fields)),
        )

    resolved: list[dict[str, Any]] = []
    invalid: list[str] = []
    for item in config:
        name = str(item.get("field_name", ""))
        field = fields_by_name.get(name)
        if field is None or field.trashed or name in hidden:
            invalid.append(name)
            continue
        resolved.append(_enrich(item, field))
    return resolved, invalid


def filter_payload_keys(
    db: Session,
    table: DataTable,
    user: User,
    field_config: list[dict[str, Any]],
    values: dict[str, Any],
) -> dict[str, Any]:
    """按表单配置过滤行写入载荷的键.

    规则：
    - 表级隐藏字段一律剔除（写路径与读路径同强度）
    - field_config 非空 → 仅保留配置内 visible 字段的键
    - field_config 为空 → 保留全部键（表单镜像整表）
    """
    hidden = get_hidden_field_names(db, table, user)
    filtered = {k: v for k, v in values.items() if k not in hidden}
    if field_config:
        allowed = {str(item.get("field_name")) for item in field_config if item.get("visible", True)}
        filtered = {k: v for k, v in filtered.items() if k in allowed}
    return filtered


def apply_form_defaults(
    field_config: list[dict[str, Any]],
    values: dict[str, Any],
) -> dict[str, Any]:
    """把表单配置的 default_value 注入载荷中缺失的键（不覆盖已提供值）."""
    merged = dict(values)
    for item in field_config:
        name = str(item.get("field_name", ""))
        default = item.get("default_value")
        if name and name not in merged and default is not None:
            merged[name] = default
    return merged


__all__ = [
    "apply_form_defaults",
    "filter_payload_keys",
    "resolve_form_fields",
    "validate_field_config",
]

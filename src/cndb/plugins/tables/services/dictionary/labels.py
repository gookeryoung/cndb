"""字段配置 → 人话（数据字典口径，ADR 0188）.

数据字典的读者是业务 / 评审 / 合规，不是工程师：`config` 里的
`{"options":[{"label":"A","value":"A"}]}` / `{"validation":{"pattern":"^A"}}`
必须翻译成可读文本，否则文档里只有 JSON 噪声。

口径：

- 类型标签取后端 registry 的 `FieldType.label`（唯一真相源，不新增第二份映射）；
- 未知字段类型不抛错，标签回退原值（与前端 `?? type` 兜底语义一致）；
- 所有翻译函数都**不读数据库**，跨表解析（表名 / 字段名）由调用方把解析好的上下文传进来。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.tables.field_types.registry import default_registry
from cndb.plugins.tables.models import DataField

#: 元数据缺失时的统一占位（I4：不省略，让缺口可见）
MISSING = "未填写"
#: 未指派责任人时的占位
UNASSIGNED = "未指派"
#: 机密字段在默认导出口径下的脱敏占位
REDACTED = "（受限）"

#: 条件必填算子 → 中文（与 `services/core/field_rules.py::REQUIRED_WHEN_OPS` 对齐）
_REQUIRED_WHEN_OPS: dict[str, str] = {
    "eq": "等于",
    "neq": "不等于",
    "in": "属于",
    "not_in": "不属于",
    "is_empty": "为空",
    "is_not_empty": "不为空",
}

#: 日期自动填充 → 中文
_AUTO_FILL_LABELS: dict[str, str] = {
    "on_create": "创建时填入当前时间",
    "on_update": "每次更新覆盖为当前时间",
}

#: 敏感级 → 中文
SENSITIVITY_LABELS: dict[str, str] = {
    "public": "公开",
    "internal": "内部",
    "confidential": "机密",
}


def field_type_label(field_type: str) -> str:
    """字段类型 → 中文标签（registry 的 `label`，未知类型回退原值）."""
    ft = default_registry.get(field_type)
    return ft.label if ft is not None and ft.label else field_type


def field_type_category(field_type: str) -> str:
    """字段类型 → 类别名（basic / numeric / date / select / link / advanced）."""
    ft = default_registry.get(field_type)
    if ft is None:
        return ""
    category = ft.category
    return category.value if hasattr(category, "value") else str(category)


def sensitivity_label(value: str | None) -> str:
    """敏感级 → 中文（空 / 脏值按「内部」，与 `FieldSensitivity.normalize` 同口径）."""
    from cndb.plugins.tables.models import FieldSensitivity

    return SENSITIVITY_LABELS.get(FieldSensitivity.normalize(value).value, "内部")


def format_default_value(field: DataField) -> str:
    """默认值 → 可读文本（自动编号模式优先，其余按原值）."""
    config: dict[str, Any] = field.config or {}
    if config.get("default_mode") == "auto_increment":
        prefix = str(config.get("increment_prefix") or "")
        padding = int(config.get("increment_padding") or 0)
        start = int(config.get("increment_start") or 1)
        number = str(start).zfill(padding) if padding else str(start)
        return f"自动编号（{prefix}{number} 起，补零 {padding} 位）"
    value = field.default_value
    if value is None or value == "":
        return MISSING
    if isinstance(value, list):
        return "、".join(str(v) for v in value) or MISSING
    return str(value)


def format_options(options: Any) -> list[dict[str, str]]:
    """枚举选项 → [{value, label, color, meaning}]（meaning 恒为占位：config 无该落点）."""
    if not isinstance(options, list):
        return []
    result: list[dict[str, str]] = []
    for item in options:
        if isinstance(item, str):
            result.append({"value": item, "label": item, "color": "", "meaning": MISSING})
            continue
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        value = item.get("value")
        result.append(
            {
                "value": str(value if value is not None else label),
                "label": label or str(value or ""),
                "color": str(item.get("color") or ""),
                "meaning": MISSING,
            }
        )
    return result


def format_validation(field: DataField) -> list[str]:
    """校验规则 → 可读句子列表（空列表 = 无规则）."""
    config: dict[str, Any] = field.config or {}
    lines: list[str] = []
    validation = config.get("validation")
    if isinstance(validation, dict) and isinstance(validation.get("pattern"), str) and validation["pattern"]:
        message = validation.get("message")
        suffix = f"（不匹配提示：{message}）" if isinstance(message, str) and message else ""
        lines.append(f"正则 {validation['pattern']}{suffix}")
    required_when = config.get("required_when")
    if isinstance(required_when, dict) and isinstance(required_when.get("field"), str) and required_when["field"]:
        op = str(required_when.get("op") or "eq")
        op_label = _REQUIRED_WHEN_OPS.get(op, op)
        expected = required_when.get("value")
        if op in ("is_empty", "is_not_empty"):
            condition = f"「{required_when['field']}」{op_label}"
        else:
            shown = "、".join(str(v) for v in expected) if isinstance(expected, list) else str(expected)
            condition = f"「{required_when['field']}」{op_label}「{shown}」"
        lines.append(f"条件必填：{condition} 时本字段必填")
    return lines


def format_value_range(field: DataField) -> str:
    """取值范围 / 格式约束 → 一行文本（无约束返回占位）."""
    config: dict[str, Any] = field.config or {}
    parts: list[str] = []
    min_value = config.get("min")
    max_value = config.get("max")
    if min_value is not None or max_value is not None:
        if min_value is not None and max_value is not None:
            parts.append(f"{min_value} ~ {max_value}")
        elif min_value is not None:
            parts.append(f"≥ {min_value}")
        else:
            parts.append(f"≤ {max_value}")
    decimals = config.get("decimals")
    if isinstance(decimals, int) and decimals > 0:
        parts.append(f"保留 {decimals} 位小数")
    if config.get("auto_fill") in _AUTO_FILL_LABELS:
        parts.append(_AUTO_FILL_LABELS[str(config["auto_fill"])])
    if field.field_type in ("attachment", "image"):
        max_size = config.get("max_size_mb")
        if max_size is not None:
            parts.append(f"单文件 ≤ {max_size} MB")
        max_count = config.get("max_count")
        if isinstance(max_count, int) and max_count > 0:
            parts.append(f"最多 {max_count} 个")
        mimes = config.get("allowed_mime_types")
        if isinstance(mimes, list) and mimes:
            parts.append(f"允许类型 {'、'.join(str(m) for m in mimes)}")
    if field.field_type in ("email", "url", "phone") and not parts:
        parts.append(f"{field_type_label(field.field_type)}格式")
    return "；".join(parts) if parts else MISSING


def format_relation(field: DataField, table_names: dict[int, str], field_names: dict[int, str]) -> str:
    """关联 / 派生字段 → 可读描述（跨表 id 由调用方解析成名字）."""
    config: dict[str, Any] = field.config or {}
    if field.field_type == "link":
        target_id = config.get("target_table_id")
        target = table_names.get(target_id, f"#{target_id}") if isinstance(target_id, int) else "未配置"
        multiple = "多选" if config.get("multiple", True) else "单选"
        parts = [f"关联「{target}」（{multiple}）"]
        display_id = config.get("display_field_id")
        if isinstance(display_id, int):
            parts.append(f"显示字段「{field_names.get(display_id, f'#{display_id}')}」")
        match_id = config.get("match_field_id")
        if isinstance(match_id, int):
            parts.append(f"匹配字段「{field_names.get(match_id, f'#{match_id}')}」")
        refs = config.get("reference_fields")
        if isinstance(refs, list) and refs:
            names = "、".join(field_names.get(r, f"#{r}") if isinstance(r, int) else str(r) for r in refs)
            parts.append(f"引用字段 {names}")
        return "；".join(parts)
    if field.field_type == "lookup":
        source_field = config.get("source_field_id")
        via_link = config.get("via_link_field_id")
        source_table = config.get("source_table_id")
        table_label = table_names.get(source_table, f"#{source_table}") if isinstance(source_table, int) else "未知"
        field_label = field_names.get(source_field, f"#{source_field}") if isinstance(source_field, int) else "未知"
        via_label = field_names.get(via_link, f"#{via_link}") if isinstance(via_link, int) else "未知"
        text = f"引用「{table_label}」的「{field_label}」（经「{via_label}」）"
        if config.get("broken"):
            text += "；源字段已失效（读取回退空值）"
        return text
    if field.field_type == "formula":
        formula = config.get("formula")
        return f"公式 {formula}" if isinstance(formula, str) and formula else MISSING
    return MISSING


def format_hidden_for(hidden_roles: list[str]) -> str:
    """字段隐藏口径 → 可读文本（空 = 无角色被隐藏）."""
    if not hidden_roles:
        return "全部角色可见"
    return f"对 {'、'.join(hidden_roles)} 隐藏"


__all__ = [
    "MISSING",
    "REDACTED",
    "SENSITIVITY_LABELS",
    "UNASSIGNED",
    "field_type_category",
    "field_type_label",
    "format_default_value",
    "format_hidden_for",
    "format_options",
    "format_relation",
    "format_validation",
    "format_value_range",
    "sensitivity_label",
]

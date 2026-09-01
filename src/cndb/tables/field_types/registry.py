"""字段类型注册表."""

from __future__ import annotations

from cndb.tables.field_types.base import FieldType, UnknownFieldTypeError

_REGISTRY: dict[str, FieldType] = {}


def register(field_type: FieldType) -> FieldType:
    """注册字段类型，同名重复注册抛 ValueError."""
    name = field_type.type_name
    if name in _REGISTRY:
        raise ValueError(f"字段类型已注册: {name}")
    _REGISTRY[name] = field_type
    return field_type


def get_field_type(type_name: str) -> FieldType:
    """按名称获取字段类型，未注册抛 UnknownFieldTypeError."""
    try:
        return _REGISTRY[type_name]
    except KeyError:
        raise UnknownFieldTypeError(f"未注册的字段类型: {type_name}") from None


def registered_types() -> tuple[str, ...]:
    """返回全部已注册类型名（按字典序）."""
    return tuple(sorted(_REGISTRY))

"""字段类型注册表 — 别名归一化、注册中心与默认注册表构建."""

from __future__ import annotations

from cndb.plugins.tables.field_types.base import FieldType
from cndb.plugins.tables.field_types.date import DateFieldType, DateTimeFieldType, TimestampFieldType
from cndb.plugins.tables.field_types.files import AttachmentFieldType
from cndb.plugins.tables.field_types.lookup import LookupFieldType
from cndb.plugins.tables.field_types.number import (
    BooleanFieldType,
    FloatFieldType,
    NumberFieldType,
    PercentageFieldType,
)
from cndb.plugins.tables.field_types.relation import LinkFieldType
from cndb.plugins.tables.field_types.select import MultiSelectFieldType, SelectFieldType
from cndb.plugins.tables.field_types.text import (
    EmailFieldType,
    JsonFieldType,
    LongTextFieldType,
    PhoneFieldType,
    TextFieldType,
    UrlFieldType,
)

# ── 字段类型别名归一化 ─────────────────────────────────

# 历史别名 → 后端 registry 真实名（向前兼容前端旧数据和存量记录）
_FIELD_TYPE_ALIASES: dict[str, str] = {
    # 前端旧名 / Django 时代名 → FastAPI 后端名
    "decimal": "float",
    "long_text": "longtext",
    "multi_select": "multiselect",
    "integer": "number",
    "checkbox": "boolean",
    "single_select": "select",
    "multi": "multiselect",
    # 大小写宽容
    "LongText": "longtext",
    "MultiSelect": "multiselect",
}


def normalize_field_type(name: str) -> str:
    """把前端传来的字段类型名归一化为后端 registry 注册的真实名.

    未知别名原样返回（由下游 registry.get 处理）。
    """
    if not isinstance(name, str):
        return str(name)
    # 先查别名表
    alias = _FIELD_TYPE_ALIASES.get(name)
    if alias is not None:
        return alias
    # 再尝试大小写不敏感匹配
    lower = name.lower()
    if lower != name:
        alias_ci = _FIELD_TYPE_ALIASES.get(lower)
        if alias_ci is not None:
            return alias_ci
    return name


class FieldTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, FieldType] = {}

    def register(self, ft: FieldType) -> FieldType:
        if isinstance(ft, type):
            ft = ft()
        if not ft.name:
            raise ValueError("FieldType 必须定义 name")
        self._types[ft.name] = ft
        return ft

    def get(self, name: str) -> FieldType | None:
        # 自动归一化字段类型别名
        return self._types.get(normalize_field_type(name))

    def all(self) -> list[FieldType]:
        return list(self._types.values())

    def choices(self) -> list[tuple[str, str]]:
        return [(ft.name, ft.label) for ft in self._types.values()]

    def unregister(self, name: str) -> None:
        """移除已注册的字段类型（供测试或插件卸载使用）."""
        self._types.pop(name, None)


def build_default_registry() -> FieldTypeRegistry:
    reg = FieldTypeRegistry()
    reg.register(TextFieldType())
    reg.register(LongTextFieldType())
    reg.register(NumberFieldType())
    reg.register(FloatFieldType())
    reg.register(BooleanFieldType())
    reg.register(DateFieldType())
    reg.register(DateTimeFieldType())
    reg.register(SelectFieldType())
    reg.register(MultiSelectFieldType())
    reg.register(EmailFieldType())
    reg.register(UrlFieldType())
    reg.register(PhoneFieldType())
    reg.register(PercentageFieldType())
    reg.register(TimestampFieldType())
    reg.register(LinkFieldType())
    reg.register(LookupFieldType())
    reg.register(AttachmentFieldType())
    reg.register(JsonFieldType())
    return reg


default_registry = build_default_registry()

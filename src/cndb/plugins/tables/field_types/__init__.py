from __future__ import annotations

import enum
from typing import Any, override

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text


class FieldTypeCategory(enum.StrEnum):
    BASIC = "basic"
    NUMERIC = "numeric"
    DATE = "date"
    SELECT = "select"
    LINK = "link"


class FieldTypeConfig(BaseModel):
    description: str = ""
    placeholder: str = ""


class FieldType:
    name: str = ""
    label: str = ""
    category: FieldTypeCategory = FieldTypeCategory.BASIC
    sqlalchemy_type: Any = String
    sqlalchemy_length: int | None = 255
    config_schema: type[FieldTypeConfig] = FieldTypeConfig

    def make_column(self, db_column_name: str, nullable: bool = True, default: Any = None) -> Column[Any]:
        col_type: Any = self.sqlalchemy_type
        if self.sqlalchemy_length is not None and col_type in (String, Text):
            col: Column[Any] = Column(db_column_name, col_type(self.sqlalchemy_length), nullable=nullable)
        else:
            col = Column(db_column_name, col_type, nullable=nullable)
        if default is not None:
            col.default = default
        return col

    def validate_value(self, value: Any, _config: dict[str, Any]) -> Any:
        if value is None:
            return None
        return value

    def default_value(self, _config: dict[str, Any]) -> Any:
        return None


class TextFieldType(FieldType):
    name = "text"
    label = "单行文本"
    category = FieldTypeCategory.BASIC
    sqlalchemy_type = String
    sqlalchemy_length = 255


class LongTextFieldType(FieldType):
    name = "longtext"
    label = "多行文本"
    category = FieldTypeCategory.BASIC
    sqlalchemy_type = Text
    sqlalchemy_length = None


class NumberFieldConfig(FieldTypeConfig):
    min: float | None = None
    max: float | None = None
    decimals: int = Field(default=0, ge=0, le=10)


class NumberFieldType(FieldType):
    name = "number"
    label = "整数"
    category = FieldTypeCategory.NUMERIC
    sqlalchemy_type = Integer
    sqlalchemy_length = None
    config_schema = NumberFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> int | None:
        if value is None:
            return None
        cfg = NumberFieldConfig(**_config)
        v = int(value)
        if cfg.min is not None and v < cfg.min:
            raise ValueError(f"值 {v} 小于最小值 {cfg.min}")
        if cfg.max is not None and v > cfg.max:
            raise ValueError(f"值 {v} 大于最大值 {cfg.max}")
        return v


class FloatFieldType(FieldType):
    name = "float"
    label = "小数"
    category = FieldTypeCategory.NUMERIC
    sqlalchemy_type = Float
    sqlalchemy_length = None
    config_schema = NumberFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> float | None:
        if value is None:
            return None
        cfg = NumberFieldConfig(**_config)
        v = float(value)
        if cfg.min is not None and v < cfg.min:
            raise ValueError(f"值 {v} 小于最小值 {cfg.min}")
        if cfg.max is not None and v > cfg.max:
            raise ValueError(f"值 {v} 大于最大值 {cfg.max}")
        return round(v, cfg.decimals)


class BooleanFieldType(FieldType):
    name = "boolean"
    label = "复选框"
    category = FieldTypeCategory.BASIC
    sqlalchemy_type = Boolean
    sqlalchemy_length = None

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1", "on")
        raise ValueError(f"无法将 {value!r} 转为布尔值")

    @override
    def default_value(self, _config: dict[str, Any]) -> bool:
        return False


class DateFieldConfig(FieldTypeConfig):
    include_time: bool = False


class DateFieldType(FieldType):
    name = "date"
    label = "日期"
    category = FieldTypeCategory.DATE
    sqlalchemy_type = Date
    sqlalchemy_length = None
    config_schema = DateFieldConfig


class DateTimeFieldType(FieldType):
    name = "datetime"
    label = "日期时间"
    category = FieldTypeCategory.DATE
    sqlalchemy_type = DateTime
    sqlalchemy_length = None
    config_schema = DateFieldConfig


class SelectFieldConfig(FieldTypeConfig):
    options: list[str] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("options 不能为空")
        return v


class SelectFieldType(FieldType):
    name = "select"
    label = "单选"
    category = FieldTypeCategory.SELECT
    sqlalchemy_type = String
    sqlalchemy_length = 255
    config_schema = SelectFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        options = _config.get("options", [])
        if value not in options:
            raise ValueError(f"{value!r} 不在可选值 {options} 中")
        return value


class MultiSelectFieldConfig(SelectFieldConfig):
    pass


class MultiSelectFieldType(FieldType):
    name = "multiselect"
    label = "多选"
    category = FieldTypeCategory.SELECT
    sqlalchemy_type = Text
    sqlalchemy_length = None
    config_schema = MultiSelectFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        options = _config.get("options", [])
        values = value if isinstance(value, list) else [value]
        for v in values:
            if v not in options:
                raise ValueError(f"{v!r} 不在可选值 {options} 中")
        return ",".join(str(v) for v in values)


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
        return self._types.get(name)

    def all(self) -> list[FieldType]:
        return list(self._types.values())

    def choices(self) -> list[tuple[str, str]]:
        return [(ft.name, ft.label) for ft in self._types.values()]

    def unregister(self, name: str) -> None:
        """移除已注册的字段类型（供测试或插件卸载使用）."""
        self._types.pop(name, None)


class LinkFieldConfig(FieldTypeConfig):
    target_table_id: int = Field(..., description="关联的目标表 ID")
    multiple: bool = Field(default=False, description="是否多选（暂只支持单选，预留）")


class LinkFieldType(FieldType):
    """关联字段类型：存储目标表某行的主键 ID."""

    name = "link"
    label = "关联"
    category = FieldTypeCategory.LINK
    sqlalchemy_type = Integer
    sqlalchemy_length = None
    config_schema = LinkFieldConfig

    @override
    def make_column(self, db_column_name: str, nullable: bool = True, default: Any = None):
        return Column(db_column_name, Integer, nullable=nullable)

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("link 字段值必须是整数（目标行 id）") from exc


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
    reg.register(LinkFieldType())
    return reg


default_registry = build_default_registry()

__all__ = [
    "BooleanFieldType",
    "DateFieldConfig",
    "DateFieldType",
    "DateTimeFieldType",
    "FieldType",
    "FieldTypeCategory",
    "FieldTypeConfig",
    "FieldTypeRegistry",
    "FloatFieldType",
    "LinkFieldConfig",
    "LinkFieldType",
    "LongTextFieldType",
    "MultiSelectFieldConfig",
    "MultiSelectFieldType",
    "NumberFieldConfig",
    "NumberFieldType",
    "SelectFieldConfig",
    "SelectFieldType",
    "TextFieldType",
    "build_default_registry",
    "default_registry",
]

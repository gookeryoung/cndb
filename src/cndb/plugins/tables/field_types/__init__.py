"""tables field_types（facade —— 只做导入导出）.

按字段类型族拆分的子模块：
- base: FieldType 基类 / 分类 / 配置基座
- text: 单行文本（自动编号）/ 多行文本 / 邮箱 / URL / 手机号 / JSON
- number: 整数 / 小数 / 复选框 / 百分比
- date: 日期 / 日期时间（自动填充）/ Unix 时间戳
- select: 单选 / 多选（含智能配色）
- relation: 关联字段
- files: 附件字段
- registry: 别名归一化 / 注册中心 / 默认注册表
"""

from __future__ import annotations

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig
from cndb.plugins.tables.field_types.date import (
    DateFieldConfig,
    DateFieldType,
    DateTimeFieldType,
    TimestampFieldType,
)
from cndb.plugins.tables.field_types.files import AttachmentFieldConfig, AttachmentFieldType
from cndb.plugins.tables.field_types.number import (
    BooleanFieldType,
    FloatFieldType,
    NumberFieldConfig,
    NumberFieldType,
    PercentageFieldConfig,
    PercentageFieldType,
)
from cndb.plugins.tables.field_types.registry import (
    _FIELD_TYPE_ALIASES,
    FieldTypeRegistry,
    build_default_registry,
    default_registry,
    normalize_field_type,
)
from cndb.plugins.tables.field_types.relation import LinkFieldConfig, LinkFieldType
from cndb.plugins.tables.field_types.select import (
    MULTI_SELECT_SPLIT_RE,
    MultiSelectFieldConfig,
    MultiSelectFieldType,
    SelectFieldConfig,
    SelectFieldType,
    SelectOption,
    split_multi_select_string,
)
from cndb.plugins.tables.field_types.text import (
    EmailFieldType,
    JsonFieldType,
    LongTextFieldType,
    PhoneFieldType,
    TextFieldConfig,
    TextFieldType,
    UrlFieldType,
)

__all__ = [
    "MULTI_SELECT_SPLIT_RE",
    "_FIELD_TYPE_ALIASES",
    "AttachmentFieldConfig",
    "AttachmentFieldType",
    "BooleanFieldType",
    "DateFieldConfig",
    "DateFieldType",
    "DateTimeFieldType",
    "EmailFieldType",
    "FieldType",
    "FieldTypeCategory",
    "FieldTypeConfig",
    "FieldTypeRegistry",
    "FloatFieldType",
    "JsonFieldType",
    "LinkFieldConfig",
    "LinkFieldType",
    "LongTextFieldType",
    "MultiSelectFieldConfig",
    "MultiSelectFieldType",
    "NumberFieldConfig",
    "NumberFieldType",
    "PercentageFieldConfig",
    "PercentageFieldType",
    "PhoneFieldType",
    "SelectFieldConfig",
    "SelectFieldType",
    "SelectOption",
    "TextFieldConfig",
    "TextFieldType",
    "TimestampFieldType",
    "UrlFieldType",
    "build_default_registry",
    "default_registry",
    "normalize_field_type",
    "split_multi_select_string",
]

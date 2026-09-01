"""字段类型系统：基类、异常与注册表.

每种字段类型实现统一接口：DDL 列类型、配置校验、值校验。
新类型通过 register() 注册即可被元数据中心识别，无需修改核心代码。
"""

from __future__ import annotations

from .base import (
    FieldType,
    FieldTypeError,
    InvalidFieldConfigError,
    InvalidFieldValueError,
    UnknownFieldTypeError,
)
from .builtin import BUILTIN_FIELD_TYPES
from .registry import get_field_type, register, registered_types

__all__ = [
    "BUILTIN_FIELD_TYPES",
    "FieldType",
    "FieldTypeError",
    "InvalidFieldConfigError",
    "InvalidFieldValueError",
    "UnknownFieldTypeError",
    "get_field_type",
    "register",
    "registered_types",
]

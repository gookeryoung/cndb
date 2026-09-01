"""字段类型基类与异常体系."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar


class FieldTypeError(Exception):
    """字段类型系统异常基类."""


class UnknownFieldTypeError(FieldTypeError):
    """未注册的字段类型."""


class InvalidFieldConfigError(FieldTypeError):
    """字段配置非法."""


class InvalidFieldValueError(FieldTypeError):
    """字段值非法."""


class FieldType(ABC):
    """字段类型接口：DDL 列类型、配置校验与值校验的统一契约."""

    type_name: ClassVar[str]

    @abstractmethod
    def db_column_type(self, config: Mapping[str, Any]) -> str:
        """返回 DDL 列类型（PostgreSQL 方言），由配置决定精度/长度等参数."""

    def validate_config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        """校验并归一化字段配置，非法时抛 InvalidFieldConfigError，默认原样拷贝."""
        if config is None:
            return {}
        if not isinstance(config, Mapping):
            raise InvalidFieldConfigError(f"{self.type_name} 的 config 必须是对象")
        return dict(config)

    def validate_value(self, value: Any, config: Mapping[str, Any]) -> Any:
        """校验写入值并返回归一化结果；None 表示空值，直接放行."""
        if value is None:
            return None
        return self.clean_value(value, config)

    @abstractmethod
    def clean_value(self, value: Any, config: Mapping[str, Any]) -> Any:
        """校验非空值并返回归一化结果，非法时抛 InvalidFieldValueError."""

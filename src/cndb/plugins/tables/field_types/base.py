"""字段类型基类 — FieldType 抽象基类、类别枚举、配置基类."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import Column, String, Text

if TYPE_CHECKING:
    from cndb.plugins.tables.models import DataField, DataTable


class FieldTypeCategory(enum.StrEnum):
    BASIC = "basic"
    NUMERIC = "numeric"
    DATE = "date"
    SELECT = "select"
    LINK = "link"
    ADVANCED = "advanced"


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
    # False 表示该类型不在源表物理表上占列（如 link 的关联表存储），DDL 引擎据此跳过建列
    has_physical_column: bool = True

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

    def parse_query_value(self, value: Any, _config: dict[str, Any]) -> Any:
        """查询参数中原始值的解析钩子（link 等类型覆盖为结构化值）."""
        return value

    def default_value(self, _config: dict[str, Any]) -> Any:
        return None

    def next_increment_value(
        self, engine: Any, table: DataTable, field: DataField, extra_seen: Sequence[str] = ()
    ) -> str | None:
        """推算自动编号默认值的下一个值；不支持自动编号的字段类型返回 None.

        Args:
            engine: 数据库引擎（供物理列扫描，基类默认实现未使用）.
            table: 数据表元数据.
            field: 字段元数据.
            extra_seen: 本批次已分配但尚未落库的值，参与编号推算（批量创建时保证逐行递增）.
        """
        _ = engine, table, field, extra_seen
        return None

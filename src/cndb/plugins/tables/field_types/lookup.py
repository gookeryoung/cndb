"""复合族字段类型 — 引用查找（lookup，跨表字段关联）.

语义：类似 SQL 多表关联后的投影列 —— 本表通过已有的 link 字段
（即"外键"，config.via_link_field_id）关联到源表行，
读取源表某字段（config.source_field_id）的值。

存储模型：值实时查询、只读、不落物理列（has_physical_column = False），
源表更新零同步成本。config.broken=True 表示源字段已失效（被删/改类型），
读取时回退 None。
"""

from __future__ import annotations

from typing import Any, override

from pydantic import Field
from sqlalchemy import Integer

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig

LOOKUP_FIELD_TYPE = "lookup"
LINK_FIELD_TYPE = "link"


class LookupFieldConfig(FieldTypeConfig):
    """lookup 字段配置：源表 / 源字段 / 借用的本表 link 字段."""

    source_table_id: int = Field(..., description="关联的源表 ID")
    source_field_id: int = Field(..., description="读取值的源字段 ID")
    via_link_field_id: int = Field(..., description="本表中指向源表的 link 字段 ID（外键角色）")
    display_field_id: int | None = Field(default=None, description="可选：源行展示字段（仅 UI 用）")
    broken: bool = Field(default=False, description="源字段已失效（被删除/改类型），读取回退 None")


class LookupFieldType(FieldType):
    """引用查找字段：跨表字段关联，值随 link 字段实时解析."""

    name = LOOKUP_FIELD_TYPE
    label = "引用查找"
    category = FieldTypeCategory.LINK
    sqlalchemy_type = Integer
    sqlalchemy_length = None
    config_schema = LookupFieldConfig
    has_physical_column = False

    @override
    def make_column(self, db_column_name: str, nullable: bool = True, default: Any = None):
        raise RuntimeError("lookup 字段无物理列，值通过关联表实时解析")

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> None:
        """lookup 字段只读：写入值一律丢弃为 None."""
        return None

"""复合族字段类型 — 表间关联（link，独立关联表存储）."""

from __future__ import annotations

from typing import Any, override

from pydantic import Field
from sqlalchemy import Integer

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig


class LinkFieldConfig(FieldTypeConfig):
    target_table_id: int = Field(..., description="关联的目标表 ID")
    multiple: bool = Field(default=True, description="是否多选（多对多关联表存储，单选由前端约束）")


class LinkFieldType(FieldType):
    """关联字段类型：表间多对多关联.

    存储模型：每个 link 字段对应一张独立关联物理表（表名由 DataField.link_table_name
    系统生成），行为 (row_id, target_row_id) 多对多；源表物理表上不占列.
    """

    name = "link"
    label = "关联"
    category = FieldTypeCategory.LINK
    sqlalchemy_type = Integer
    sqlalchemy_length = None
    config_schema = LinkFieldConfig
    has_physical_column = False

    @override
    def make_column(self, db_column_name: str, nullable: bool = True, default: Any = None):
        raise RuntimeError("link 字段无物理列，应通过 DDL 引擎创建关联表")

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> list[int]:
        """校验值为目标行 id 列表：全为正整数（拒绝 bool），去重保序."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("link 字段的值必须是目标行 id 列表")
        result: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError(f"link 字段的关联项必须是正整数行 id，收到 {item!r}")
            if item not in result:
                result.append(item)
        return result

    @override
    def parse_query_value(self, value: Any, _config: dict[str, Any]) -> Any:
        """查询参数中的 id 集合字符串（分号分隔）解析为整数列表."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return list[int]()
        try:
            return [int(part) for part in text.split(";")]
        except ValueError as exc:
            raise ValueError("link 字段的查询值必须是分号分隔的行 id") from exc

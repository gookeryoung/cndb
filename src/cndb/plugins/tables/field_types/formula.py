"""派生字段（formula）—— 按已有字段的公式 / 函数实时计算，不落物理列.

语义：值在读取时由受限公式引擎（analytics 公式引擎）按行计算，**只读**；
公式引用表内字段名，支持数字、四则运算、白名单标量 / 聚合 / 窗口函数。

存储模型：``has_physical_column=False``，数据库不建列；读取行后由
``services/core/formulas.py`` 附加结果。公式字段之间可相互引用（按字段顺序计算）。
"""

from __future__ import annotations

from typing import Any, override

from pydantic import Field

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig

FORMULA_FIELD_TYPE = "formula"


class FormulaFieldConfig(FieldTypeConfig):
    """派生字段配置：公式表达式 + 可选小数位."""

    formula: str = Field(..., min_length=1, max_length=500, description="公式，如 round([金额] / [数量], 2)")
    decimals: int | None = Field(default=None, ge=0, le=10, description="结果保留小数位；空 = 不额外取整")


class FormulaFieldType(FieldType):
    """派生字段：读取时按公式计算，写入一律忽略."""

    name = FORMULA_FIELD_TYPE
    label = "派生字段"
    category = FieldTypeCategory.ADVANCED
    config_schema = FormulaFieldConfig
    has_physical_column = False

    @override
    def make_column(self, db_column_name: str, nullable: bool = True, default: Any = None):
        raise RuntimeError("formula 字段无物理列，值在读取时计算")

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> None:
        """派生字段只读：写入值一律丢弃为 None."""
        return None


__all__ = ["FORMULA_FIELD_TYPE", "FormulaFieldConfig", "FormulaFieldType"]

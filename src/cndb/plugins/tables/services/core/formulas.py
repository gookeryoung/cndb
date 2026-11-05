"""派生字段（formula）的读取期计算.

公式引擎复用 analytics 的受限表达式求值器（tokenizer + 白名单 AST，无 eval），
只在行响应阶段计算，不落物理列。``lookup`` 先解析、formula 后计算，
因此公式可引用引用字段；formula 字段之间按字段顺序依次计算，也可相互引用。
"""

from __future__ import annotations

import logging
from typing import Any

from cndb.plugins.tables.models import DataField, DataTable

logger = logging.getLogger(__name__)

FORMULA_FIELD_TYPE = "formula"


def is_formula_field(field: DataField) -> bool:
    return field.field_type == FORMULA_FIELD_TYPE


def formula_fields(table: DataTable) -> list[DataField]:
    return [f for f in table.active_fields() if is_formula_field(f)]


def attach_formula_values(table: DataTable, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为行响应附加 formula 字段的计算值；无公式 / 空结果时原样返回."""
    fields = formula_fields(table)
    if not fields or not rows:
        return rows

    # 延迟导入：analytics 依赖 tables，模块级导入会形成插件循环
    from cndb.plugins.analytics.services.formula import FormulaError, evaluate_column

    names = {f.name for f in table.active_fields()}
    for field in fields:
        config = field.config or {}
        expr = str(config.get("formula") or "").strip()
        if not expr:
            for row in rows:
                row[field.name] = None
            continue
        try:
            values = evaluate_column(expr, rows, names)
        except FormulaError as exc:
            logger.warning("[formulas] 字段 %s 公式求值失败: %s", field.name, exc)
            values = [None] * len(rows)
        except Exception:
            logger.warning("[formulas] 字段 %s 公式异常，回退空值", field.name, exc_info=True)
            values = [None] * len(rows)
        decimals = config.get("decimals")
        for row, value in zip(rows, values, strict=False):
            if value is not None and isinstance(decimals, int) and 0 <= decimals <= 10:
                value = round(value, decimals)
            row[field.name] = value
    return rows


__all__ = ["FORMULA_FIELD_TYPE", "attach_formula_values", "formula_fields", "is_formula_field"]

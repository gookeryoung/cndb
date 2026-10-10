"""数值族字段类型 — 整数 / 小数 / 复选框 / 百分比."""

from __future__ import annotations

import logging
import math
from typing import Any, override

from pydantic import Field
from sqlalchemy import Boolean, Float, Integer

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig

logger = logging.getLogger(__name__)


class NumberFieldConfig(FieldTypeConfig):
    min: float | None = None
    max: float | None = None
    decimals: int = Field(default=0, ge=0, le=10)


def _normalize_numeric_string(value: str) -> str | None:
    """把带千分位/货币符号/会计负号/全角符号的数字字符串归一为纯数字串.

    惰性导入 :func:`transfer._normalize_numeric` 打破循环依赖
    （transfer → records/models → field_types），复用推断层同一套归一逻辑，
    保证"识别出的格式一定能转换"。
    """
    from cndb.plugins.tables.services.transfer import _normalize_numeric

    return _normalize_numeric(value)


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
        if isinstance(value, str):
            # 字符串经千分位/货币/会计负数/全角归一后再转整数（与推断层识别值域一致）
            normalized = _normalize_numeric_string(value)
            if normalized is None:
                raise ValueError(f"无法将 {value!r} 转为整数")
            value = normalized
        cfg = NumberFieldConfig(**_config)
        try:
            v = int(value)
        except ValueError:
            # 科学计数法整数值（如 1.5e10）：仅当 float 值恰为整数时接受，否则维持报错
            f = float(value)
            if not f.is_integer():
                raise ValueError(f"无法将 {value!r} 转为整数") from None
            v = int(f)
        if cfg.min is not None and v < cfg.min:
            raise ValueError(f"值 {v} 小于最小值 {cfg.min}")
        if cfg.max is not None and v > cfg.max:
            raise ValueError(f"值 {v} 大于最大值 {cfg.max}")
        return v

    @override
    def parse_query_value(self, value: Any, _config: dict[str, Any]) -> Any:
        """筛选值归一：字符串经千分位/货币/全角归一后转整数，失败回退原值并记 warning.

        物理列为 Integer，字符串筛选值直接比较在 SQLite 中永远不命中；
        不做 min/max 范围校验（超范围筛选值仅匹配不到行，不视为非法输入）。
        """
        if isinstance(value, str) and value.strip():
            normalized = _normalize_numeric_string(value.strip())
            if normalized is not None:
                try:
                    return int(normalized)
                except ValueError:
                    pass  # 归一后含小数部分：整数列匹配不到，回退原值
            logger.warning("整数筛选值无法解析，按原值比较: %r", value)
        return value


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
        if isinstance(value, str):
            # 字符串经千分位/货币/会计负数/全角归一后再转小数（与推断层识别值域一致）
            normalized = _normalize_numeric_string(value)
            if normalized is None:
                raise ValueError(f"无法将 {value!r} 转为小数")
            value = normalized
        cfg = NumberFieldConfig(**_config)
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"无法将 {value!r} 转为小数") from exc
        # 拒绝 NaN / 无穷大：这些值能入库但 FastAPI JSONResponse 序列化时会炸，
        # 导致全部行列表/详情端点返回 500；PercentageFieldType 已有同样守卫
        if not math.isfinite(v):
            raise ValueError(f"小数必须是有限数字，收到 {value!r}")
        if cfg.min is not None and v < cfg.min:
            raise ValueError(f"值 {v} 小于最小值 {cfg.min}")
        if cfg.max is not None and v > cfg.max:
            raise ValueError(f"值 {v} 大于最大值 {cfg.max}")
        return round(v, cfg.decimals)

    @override
    def parse_query_value(self, value: Any, _config: dict[str, Any]) -> Any:
        """筛选值归一：字符串经千分位/货币/全角归一后转小数，失败回退原值并记 warning."""
        if isinstance(value, str) and value.strip():
            normalized = _normalize_numeric_string(value.strip())
            if normalized is not None:
                try:
                    return float(normalized)
                except ValueError:
                    pass  # 理论上归一为纯数字串后必可转 float，此处防御
            logger.warning("小数筛选值无法解析，按原值比较: %r", value)
        return value


# 布尔字符串真值域（与 transfer._BOOLEAN_TRUE_VALUES 一致，测试矩阵双向锁定；
# 未匹配字符串沿用历史行为返回 False，不抛错）
_BOOLEAN_TRUE_STRINGS = frozenset({"true", "yes", "1", "on", "是", "真", "对", "y", "t", "√"})


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
            # 中文 是/真/对、单字母 Y/T、对勾 √ 等均识别为真值（与推断层值域一致）
            return value.strip().lower() in _BOOLEAN_TRUE_STRINGS
        raise ValueError(f"无法将 {value!r} 转为布尔值")

    @override
    def parse_query_value(self, value: Any, _config: dict[str, Any]) -> Any:
        """过滤值归一为真实布尔（列表逐项归一）.

        布尔物理列存 SQLite 1/0，过滤值若是字符串（种子视图 '是'、历史过滤器的
        'true' 等）直接与列比较永远不命中 —— 与写入侧 validate_value 共用同一
        值域，保证"勾选后行立即出现在过滤视图中"。
        """
        if isinstance(value, (list, tuple)):
            return [self.validate_value(v, _config) for v in value]
        return self.validate_value(value, _config)

    @override
    def default_value(self, _config: dict[str, Any]) -> bool:
        return False


# ── percentage ──────────────────────────────────────


class PercentageFieldConfig(FieldTypeConfig):
    decimals: int = Field(default=0, ge=0, le=5)


class PercentageFieldType(FieldType):
    """百分比字段 —— 存储 0.0 ~ 1.0 的比例值浮点数.

    存储约定：裸数字（无 % 后缀）必须是 0~1 比例值；%-后缀字符串视为
    显式用户意图，可为任意有限比例（``-12.5%`` → -0.125、``200%`` → 2.0），
    避免"负百分比/超 100% 行导致混合列整表导入失败"。
    """

    name = "percentage"
    label = "百分比"
    category = FieldTypeCategory.NUMERIC
    sqlalchemy_type = Float
    sqlalchemy_length = None
    config_schema = PercentageFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> float | None:
        if value is None:
            return None
        # 字符串带百分号（含全角％）→ 剥离后除以 100 存为比例值（与推断层 "85%" → percentage 对齐）；
        # 显式 % 后缀即用户意图，不受 0~1 值域限制，但须排除 NaN/inf
        if isinstance(value, str):
            text = value.strip()
            if text.endswith(("%", "％")):
                try:
                    num = float(text[:-1].strip()) / 100
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"百分比必须是数字: {value!r}") from exc
                if not math.isfinite(num):
                    raise ValueError(f"百分比必须是有限数字: {value!r}")
                return num
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"百分比必须是数字: {value!r}") from exc
        # 裸数字保留 0~1 值域防护（无 % 后缀即无显式意图，超出比例值域视为数据错误；
        # NaN/inf 因比较为 False 同样在此拒绝）
        if not (0 <= num <= 1):
            raise ValueError(f"百分比必须在 0~1 之间（存储比例值），收到 {num}")
        return num

    @override
    def parse_query_value(self, value: Any, _config: dict[str, Any]) -> Any:
        """筛选值归一：'%' 后缀字符串 → ÷100 比例值，其余数字串转 float.

        物理列存 0~1 比例值浮点数，'85%' 这类显式意图值须除以 100 才能命中；
        解析失败回退原值并记 warning（不做 0~1 值域校验，超范围仅匹配不到行）。
        """
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text.endswith(("%", "％")):
                try:
                    return float(text[:-1].strip()) / 100
                except (TypeError, ValueError):
                    logger.warning("百分比筛选值无法解析，按原值比较: %r", value)
                return value
            try:
                return float(text)
            except (TypeError, ValueError):
                logger.warning("百分比筛选值无法解析，按原值比较: %r", value)
        return value

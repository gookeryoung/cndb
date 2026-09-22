"""日期族字段类型 — 日期 / 日期时间（自动填充）/ Unix 时间戳."""

from __future__ import annotations

import re
from typing import Any, override

from pydantic import Field
from sqlalchemy import Date, DateTime, Integer

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig

# ── 日期字段（含自动填充）─────────────────────────────────


# 日期字符串解析格式清单（与 transfer 推断层识别的格式一一对应，测试矩阵双向锁定）
_DATE_PARSE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",  # 2024-01-15
    "%Y/%m/%d",  # 2024/1/15
    "%Y.%m.%d",  # 2024.1.15
    "%Y%m%d",  # 20240115 紧凑
    "%Y年%m月%d日",  # 2024年1月15日
    "%Y年%m月%d",  # 2024年1月15（"日"省略）
    "%m/%d/%Y",  # 1/15/2024 美式
    "%b %d, %Y",  # Jan 15, 2024
    "%b %d %Y",  # Jan 15 2024
    "%d %b %Y",  # 15 Jan 2024
    "%d %b, %Y",  # 15 Jan, 2024
    "%B %d, %Y",  # January 15, 2024 全称
    "%B %d %Y",
    "%d %B %Y",
    "%d %B, %Y",
)

# 日期时间字符串解析格式清单（与 transfer 推断层识别的格式一一对应）
_DATETIME_PARSE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",  # 微秒变体
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y/%m/%d %H:%M",  # 斜杠日期 + 时间
    "%Y/%m/%d %H:%M:%S",
    "%Y.%m.%d %H:%M",  # 点分隔日期 + 时间
    "%Y.%m.%d %H:%M:%S",
)

# ISO 8601 时区后缀（Z 或 ±HH:MM / ±HHMM）—— 解析前剥离为无时区本地语义
_TZ_SUFFIX_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")

# 英文月缩写 "Sept"（strptime %b 仅认 "Sep"，全称 september 走 %B 不受影响）
_SEPT_ABBR_RE = re.compile(r"sept\b", re.IGNORECASE)


class DateFieldConfig(FieldTypeConfig):
    """日期/日期时间字段的可配置项.

    Attributes:
        include_time: 是否包含时间部分（仅 date 类型使用）.
        auto_fill: 自动填充时机。空字符串表示不自动填充，"on_create" 表示创建时填入当前时间，
            "on_update" 表示每次更新都覆盖为当前时间（适合"更新时间"戳）.
    """

    include_time: bool = False
    auto_fill: str = Field(default="", pattern=r"^(on_create|on_update)?$")

    def should_auto_fill(self, *, for_update: bool) -> bool:
        """判断当前操作是否需要自动填充."""
        if self.auto_fill == "on_update":
            return True  # 更新时总填充
        if self.auto_fill == "on_create":
            return not for_update
        return False

    def auto_value(self) -> Any:  # pragma: no cover
        """返回当前的日期/时间值（由子类 FieldType 调用，各自决定返回 date 还是 datetime）."""
        # 占位：实际值由 DateFieldType / DateTimeFieldType 覆盖 default_value 产生
        return None


class DateFieldType(FieldType):
    name = "date"
    label = "日期"
    category = FieldTypeCategory.DATE
    sqlalchemy_type = Date
    sqlalchemy_length = None
    config_schema = DateFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> Any:
        if value is None or value == "":
            return None
        from datetime import date, datetime

        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()  # pragma: no cover - datetime 输入分支待补测试
        if isinstance(value, str):
            text = value.strip()
            # "Sept" 是常见英文月缩写但 strptime %b 不识别，归一为 "Sep"（全称 september 不受影响）
            text = _SEPT_ABBR_RE.sub("Sep", text)
            for fmt in _DATE_PARSE_FORMATS:
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"日期格式错误: {value}")
        raise ValueError(f"不支持的日期类型: {type(value)}")

    @override
    def default_value(self, _config: dict[str, Any]) -> Any:
        cfg = DateFieldConfig(**_config)
        if cfg.should_auto_fill(for_update=False):
            from datetime import date

            return date.today()
        return None


class DateTimeFieldType(FieldType):
    name = "datetime"
    label = "日期时间"
    category = FieldTypeCategory.DATE
    sqlalchemy_type = DateTime
    sqlalchemy_length = None
    config_schema = DateFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> Any:
        if value is None or value == "":
            return None
        from datetime import date, datetime

        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, str):
            # 剥离 ISO 8601 时区后缀（Z / ±HH:MM），按无时区本地语义存储
            text = _TZ_SUFFIX_RE.sub("", value.strip())
            for fmt in _DATETIME_PARSE_FORMATS:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            raise ValueError(f"日期时间格式错误: {value}")
        raise ValueError(f"不支持的日期时间类型: {type(value)}")

    @override
    def default_value(self, _config: dict[str, Any]) -> Any:
        cfg = DateFieldConfig(**_config)
        if cfg.should_auto_fill(for_update=False):
            from datetime import UTC, datetime

            return datetime.now(UTC).replace(tzinfo=None)
        return None


# ── timestamp ───────────────────────────────────────


class TimestampFieldType(FieldType):
    """Unix 时间戳字段 —— 存储整数秒."""

    name = "timestamp"
    label = "时间戳"
    category = FieldTypeCategory.DATE
    sqlalchemy_type = Integer
    sqlalchemy_length = None

    # 秒级上限 4102444800（2100-01-01），毫秒级上限为秒级 ×1000；
    # 与 transfer._TS_EPOCH_* 推断候选值域双向锁定
    _TS_MAX_SEC = 4102444800
    _TS_MAX_MS = 4102444800000

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("时间戳必须是整数秒")
        try:
            ts = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"时间戳必须是整数秒: {value!r}") from exc
        if ts < 0:
            raise ValueError(f"时间戳不能为负数: {ts}")
        if ts <= self._TS_MAX_SEC:
            return ts
        # 毫秒区间归一为整数秒落库（截断到秒是标准行为）；
        # 秒级上界 +1（4102444801）恰落毫秒区间，按毫秒归一语义处理
        if ts <= self._TS_MAX_MS:
            return ts // 1000
        raise ValueError(f"时间戳超出合理范围 (0~{self._TS_MAX_SEC} 秒 或 ~{self._TS_MAX_MS} 毫秒): {ts}")

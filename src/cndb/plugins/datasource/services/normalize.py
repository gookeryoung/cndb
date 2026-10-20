"""Normalizer —— 字段映射（改名 / 丢弃）+ 类型归一.

映射格式沿用 ``importing/api_config_loader.py`` 的 ``field_mapping`` 约定：

.. code-block:: python

    field_mapping = {
        "temp": {"name": "temperature", "field_type": "float"},
        "city": {"name": "city", "field_type": "text"},
        "raw_json": None,          # 丢弃该字段
    }

未在映射中出现的字段按原名保留（声明式只覆盖需要改的部分）。类型归一失败
**不丢整行**：该字段降级为 ``None`` 并记一条失败明细，供运行记录统计 partial。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from cndb.plugins.datasource.providers.base import FieldTransform

logger = logging.getLogger(__name__)

# 支持的目标类型（与 tables 字段类型的基础子集对齐；其余按 text 处理）
FieldType = str

_TRUE_TOKENS = {"1", "true", "yes", "y", "on", "是", "真"}
_FALSE_TOKENS = {"0", "false", "no", "n", "off", "否", "假"}
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y%m%d%H%M%S",
    "%Y-%m-%d %H:%M",
)


@dataclass(slots=True)
class NormalizeFailure:
    """单字段归一失败明细（进 datasource_sync_run.detail）."""

    row_index: int
    field: str
    raw: Any
    reason: str


@dataclass(slots=True)
class NormalizeResult:
    """归一结果：成功行 + 丢弃字段数 + 失败明细."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    dropped_fields: int = 0
    failures: list[NormalizeFailure] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        """被 ``field_mapping`` 显式丢弃的字段数（兼容 NormalizeLike 契约）."""
        return self.dropped_fields

    @property
    def failed(self) -> int:
        """归一失败的字段次数."""
        return len(self.failures)


def apply_field_mapping(
    rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, FieldTransform | None],
) -> NormalizeResult:
    """按映射改名 / 丢弃 / 类型归一.

    空映射时只做浅拷贝（保持列名与值原样）。
    """
    result = NormalizeResult()
    if not mapping:
        result.rows = [dict(row) for row in rows]
        return result

    dropped_names = {name for name, transform in mapping.items() if transform is None}
    result.dropped_fields = len(dropped_names)

    for row_index, row in enumerate(rows):
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if key in dropped_names:
                continue
            transform = mapping.get(key)
            if transform is None:
                normalized[key] = value
                continue
            coerced, reason = coerce_value(value, transform.field_type)
            if reason is not None:
                result.failures.append(
                    NormalizeFailure(row_index=row_index, field=transform.name, raw=value, reason=reason)
                )
            normalized[transform.name] = coerced
        result.rows.append(normalized)
    return result


def coerce_value(value: Any, field_type: FieldType) -> tuple[Any, str | None]:
    """把单个值归一为目标类型.

    Returns:
        ``(归一后的值, 失败原因)``；失败时值为 ``None``、原因为非空字符串。
    """
    if value is None:
        return None, None
    kind = (field_type or "text").strip().lower()
    if kind in ("text", "string", "str"):
        return _to_text(value), None
    if kind in ("int", "integer", "number"):
        return _to_int(value)
    if kind in ("float", "decimal"):
        return _to_float(value)
    if kind == "date":
        return _to_date(value)
    if kind in ("datetime", "timestamp"):
        return _to_datetime(value)
    if kind in ("bool", "boolean"):
        return _to_bool(value)
    if kind == "json":
        return _to_json(value)
    # 未知类型按文本兜底，避免整列丢失
    logger.debug("未知目标类型 %r，按 text 处理", field_type)
    return _to_text(value), None


def _to_json(value: Any) -> tuple[str | None, str | None]:
    """JSON 列归一：字符串先校验合法性，对象/数组序列化为紧凑文本.

    与 ``JsonFieldType.validate_value`` 保持同一存储口径（物理列为 Text），
    非法 JSON 记录失败明细并降级为 None，不阻塞同批其他字段。
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, None
        try:
            json.loads(text)
        except (TypeError, ValueError) as exc:
            return None, f"不是合法 JSON: {exc}"
        return text, None
    try:
        return json.dumps(value, ensure_ascii=False, default=str), None
    except (TypeError, ValueError) as exc:  # pragma: no cover - default=str 已兜底
        return None, f"无法序列化为 JSON: {exc}"


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str 已兜底
        return str(value)


def _to_int(value: Any) -> tuple[int | None, str | None]:
    if isinstance(value, bool):
        return int(value), None
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        return int(value), None
    text = str(value).strip().replace(",", "")
    if not text:
        return None, None
    try:
        return int(float(text)), None
    except (TypeError, ValueError):
        return None, f"无法转为整数: {value!r}"


def _to_float(value: Any) -> tuple[float | None, str | None]:
    if isinstance(value, bool):
        return float(value), None
    if isinstance(value, (int, float)):
        return float(value), None
    text = str(value).strip().replace(",", "")
    if not text:
        return None, None
    try:
        return float(text), None
    except (TypeError, ValueError):
        return None, f"无法转为数值: {value!r}"


def _to_date(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, datetime):
        return value.date().isoformat(), None
    if isinstance(value, date):
        return value.isoformat(), None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = _from_epoch(value)
        if converted is not None:
            return converted.date().isoformat(), None
    text = str(value).strip()
    if not text:
        return None, None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat(), None
        except ValueError:
            continue
    parsed = _parse_iso_datetime(text)
    if parsed is not None:
        return parsed.date().isoformat(), None
    return None, f"无法转为日期: {value!r}"


def _to_datetime(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S"), None
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).strftime("%Y-%m-%d %H:%M:%S"), None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = _from_epoch(value)
        if converted is not None:
            return converted.strftime("%Y-%m-%d %H:%M:%S"), None
    text = str(value).strip()
    if not text:
        return None, None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S"), None
        except ValueError:
            continue
    parsed = _parse_iso_datetime(text)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d %H:%M:%S"), None
    return None, f"无法转为时间: {value!r}"


def _to_bool(value: Any) -> tuple[bool | None, str | None]:
    if isinstance(value, bool):
        return value, None
    text = str(value).strip().lower()
    if text in _TRUE_TOKENS:
        return True, None
    if text in _FALSE_TOKENS:
        return False, None
    if not text:
        return None, None
    return None, f"无法转为布尔: {value!r}"


def _parse_iso_datetime(text: str) -> datetime | None:
    candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _from_epoch(value: float) -> datetime | None:
    """epoch 秒 / 毫秒 → datetime（>1e11 视为毫秒）."""
    seconds = value / 1000.0 if abs(value) > 1e11 else float(value)
    try:
        return datetime.fromtimestamp(seconds)
    except (OverflowError, OSError, ValueError):
        return None


__all__ = [
    "NormalizeFailure",
    "NormalizeResult",
    "apply_field_mapping",
    "coerce_value",
]

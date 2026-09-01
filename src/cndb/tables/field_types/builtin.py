"""内置字段类型集合：文本/长文本/数值/布尔/日期/单选/多选/邮箱/URL.

模块导入时完成注册，field_types 包的 __init__ 导入本模块即触发。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar

from cndb.tables.field_types.base import (
    FieldType,
    InvalidFieldConfigError,
    InvalidFieldValueError,
)
from cndb.tables.field_types.registry import register

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^https?://\S+$")

# 数值字段默认精度与标度
_DEFAULT_PRECISION = 10
_DEFAULT_SCALE = 2
# 选项字段的选项数量上限
_MAX_CHOICES = 200


def _require_int(value: Any, key: str, minimum: int, maximum: int, type_name: str) -> int:
    """校验配置项为 [minimum, maximum] 内的整数，返回该整数."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidFieldConfigError(f"{type_name} 的 {key} 必须是整数")
    if not minimum <= value <= maximum:
        raise InvalidFieldConfigError(f"{type_name} 的 {key} 须在 {minimum} 到 {maximum} 之间")
    return value


class TextField(FieldType):
    """单行文本：可配置最大长度."""

    type_name: ClassVar[str] = "text"
    _default_max_length = 255
    _max_length_limit = 1000

    def db_column_type(self, config: Mapping[str, Any]) -> str:
        """返回 varchar(n)."""
        return f"varchar({config.get('max_length', self._default_max_length)})"

    def validate_config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        """校验 max_length 并填充默认值."""
        config = super().validate_config(config)
        max_length = config.get("max_length", self._default_max_length)
        max_length = _require_int(max_length, "max_length", 1, self._max_length_limit, self.type_name)
        return {"max_length": max_length}

    def clean_value(self, value: Any, config: Mapping[str, Any]) -> Any:
        """校验字符串类型与长度，去除首尾空白."""
        if not isinstance(value, str):
            raise InvalidFieldValueError("text 字段的值必须是字符串")
        value = value.strip()
        if len(value) > config.get("max_length", self._default_max_length):
            raise InvalidFieldValueError("text 字段的值超出最大长度")
        return value


class LongTextField(FieldType):
    """长文本：无长度限制."""

    type_name: ClassVar[str] = "long_text"

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 text."""
        return "text"

    def clean_value(self, value: Any, _config: Mapping[str, Any]) -> Any:
        """校验字符串类型，去除首尾空白."""
        if not isinstance(value, str):
            raise InvalidFieldValueError("long_text 字段的值必须是字符串")
        return value.strip()


class NumberField(FieldType):
    """数值：可配置精度（总位数）与标度（小数位数）."""

    type_name: ClassVar[str] = "number"
    _precision_limit = 38

    def db_column_type(self, config: Mapping[str, Any]) -> str:
        """返回 numeric(precision, scale)."""
        return f"numeric({config.get('precision', _DEFAULT_PRECISION)}, {config.get('scale', _DEFAULT_SCALE)})"

    def validate_config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        """校验 precision 与 scale 的取值范围及相对关系."""
        config = super().validate_config(config)
        precision = _require_int(
            config.get("precision", _DEFAULT_PRECISION), "precision", 1, self._precision_limit, self.type_name
        )
        scale = _require_int(config.get("scale", _DEFAULT_SCALE), "scale", 0, precision, self.type_name)
        return {"precision": precision, "scale": scale}

    def clean_value(self, value: Any, config: Mapping[str, Any]) -> Any:
        """接受 int/float/Decimal（拒绝 bool），按标度四舍五入并校验精度."""
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise InvalidFieldValueError("number 字段的值必须是数字")
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidFieldValueError("number 字段的值必须是有限数")
        scale = config.get("scale", _DEFAULT_SCALE)
        precision = config.get("precision", _DEFAULT_PRECISION)
        quantized = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        if len(quantized.as_tuple().digits) > precision:
            raise InvalidFieldValueError("number 字段的值超出精度范围")
        return quantized


class BooleanField(FieldType):
    """布尔值：接受 bool 及 0/1 整数."""

    type_name: ClassVar[str] = "boolean"

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 boolean."""
        return "boolean"

    def clean_value(self, value: Any, _config: Mapping[str, Any]) -> Any:
        """bool 直接放行，0/1 整数归一化为 bool."""
        if isinstance(value, bool):
            return value
        if value == 0:
            return False
        if value == 1:
            return True
        raise InvalidFieldValueError("boolean 字段的值必须是布尔值")


class DateField(FieldType):
    """日期：接受 date/datetime 实例或 ISO 格式字符串."""

    type_name: ClassVar[str] = "date"

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 date."""
        return "date"

    def clean_value(self, value: Any, _config: Mapping[str, Any]) -> Any:
        """datetime 取日期部分，字符串按 ISO 格式解析."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise InvalidFieldValueError("date 字段的值必须是 YYYY-MM-DD 格式") from exc
        raise InvalidFieldValueError("date 字段的值必须是日期或 ISO 格式字符串")


class _BaseSelectField(FieldType):
    """选项类字段公共基类：choices 配置校验."""

    def _validate_choices(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        """校验 choices：非空、全为非空字符串、不重复."""
        config = super().validate_config(config)
        choices = config.get("choices")
        if not isinstance(choices, list) or not choices:
            raise InvalidFieldConfigError(f"{self.type_name} 的 choices 必须是非空列表")
        if len(choices) > _MAX_CHOICES:
            raise InvalidFieldConfigError(f"{self.type_name} 的选项数量不得超过 {_MAX_CHOICES}")
        for choice in choices:
            if not isinstance(choice, str) or not choice.strip():
                raise InvalidFieldConfigError(f"{self.type_name} 的选项必须是非空字符串")
        if len(set(choices)) != len(choices):
            raise InvalidFieldConfigError(f"{self.type_name} 的选项不能重复")
        return {"choices": choices}

    def _check_choice(self, value: str, config: Mapping[str, Any]) -> None:
        """校验值在选项列表内."""
        if value not in config.get("choices", []):
            raise InvalidFieldValueError(f"{self.type_name} 字段的值不在选项范围内")


class SingleSelectField(_BaseSelectField):
    """单选：值必须为选项之一."""

    type_name: ClassVar[str] = "single_select"

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 varchar(255)."""
        return "varchar(255)"

    def validate_config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        """校验 choices 配置."""
        return self._validate_choices(config)

    def clean_value(self, value: Any, config: Mapping[str, Any]) -> Any:
        """校验字符串类型且在选项内."""
        if not isinstance(value, str):
            raise InvalidFieldValueError("single_select 字段的值必须是字符串")
        self._check_choice(value, config)
        return value


class MultiSelectField(_BaseSelectField):
    """多选：值为字符串列表，逐项校验并去重保序."""

    type_name: ClassVar[str] = "multi_select"

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 jsonb."""
        return "jsonb"

    def validate_config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        """校验 choices 配置."""
        return self._validate_choices(config)

    def clean_value(self, value: Any, config: Mapping[str, Any]) -> Any:
        """校验列表内各项均在选项内，去重保序."""
        if not isinstance(value, list):
            raise InvalidFieldValueError("multi_select 字段的值必须是列表")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise InvalidFieldValueError("multi_select 字段的选项必须是字符串")
            self._check_choice(item, config)
            if item not in result:
                result.append(item)
        return result


class EmailField(FieldType):
    """邮箱：简单格式校验，长度上限 254."""

    type_name: ClassVar[str] = "email"
    _max_length = 254

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 varchar(254)."""
        return "varchar(254)"

    def clean_value(self, value: Any, _config: Mapping[str, Any]) -> Any:
        """正则校验邮箱格式."""
        if not isinstance(value, str) or len(value) > self._max_length or not _EMAIL_RE.match(value):
            raise InvalidFieldValueError("email 字段的值必须是合法邮箱地址")
        return value


class URLField(FieldType):
    """URL：仅接受 http/https 协议，长度上限 2000."""

    type_name: ClassVar[str] = "url"
    _max_length = 2000

    def db_column_type(self, _config: Mapping[str, Any]) -> str:
        """返回 varchar(2000)."""
        return "varchar(2000)"

    def clean_value(self, value: Any, _config: Mapping[str, Any]) -> Any:
        """正则校验 http(s) URL."""
        if not isinstance(value, str) or len(value) > self._max_length or not _URL_RE.match(value):
            raise InvalidFieldValueError("url 字段的值必须是 http(s) 链接")
        return value


# 内置类型实例：包导入时逐个注册
BUILTIN_FIELD_TYPES: tuple[FieldType, ...] = (
    TextField(),
    LongTextField(),
    NumberField(),
    BooleanField(),
    DateField(),
    SingleSelectField(),
    MultiSelectField(),
    EmailField(),
    URLField(),
)

for _field_type in BUILTIN_FIELD_TYPES:
    register(_field_type)

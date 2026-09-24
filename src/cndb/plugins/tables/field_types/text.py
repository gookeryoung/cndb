"""文本族字段类型 — 单行文本（自动编号）/ 多行文本 / 邮箱 / 链接 / 手机号 / JSON."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, override

from pydantic import Field
from sqlalchemy import String, Text, text

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig

if TYPE_CHECKING:
    from cndb.plugins.tables.models import DataField, DataTable


class TextFieldConfig(FieldTypeConfig):
    """单行文本字段的可配置项.

    Attributes:
        default_mode: 默认值模式。空字符串表示静态默认值（default_value），
            "auto_increment" 表示按「前缀 + 补零编号」自动生成（如 PRJ-0001），
            建行时由后端按库内已有数据推算下一编号.
        increment_prefix: 自动编号前缀，如 "PRJ-"（可为空）.
        increment_padding: 编号数字补零位数（0 表示不补零）.
        increment_start: 起始编号（库内无匹配值时使用）.
    """

    default_mode: str = Field(default="", pattern=r"^(auto_increment)?$")
    increment_prefix: str = ""
    increment_padding: int = Field(default=4, ge=0, le=10)
    increment_start: int = Field(default=1, ge=0)


class TextFieldType(FieldType):
    name = "text"
    label = "单行文本"
    category = FieldTypeCategory.BASIC
    sqlalchemy_type = String
    sqlalchemy_length = 255
    config_schema = TextFieldConfig

    @override
    def next_increment_value(
        self, engine: Any, table: DataTable, field: DataField, extra_seen: Sequence[str] = ()
    ) -> str | None:
        """推算自动编号的下一个值；未启用 auto_increment 时返回 None.

        扫描物理列全部非 NULL 值（含软删行，与唯一索引口径一致），按
        ``^{前缀转义}(\\d+)$`` 提取已有编号取最大值，下一编号为
        ``max(最大值 + 1, increment_start)``，按补零位数格式化；
        ``extra_seen``（本批次已分配未落库值）同样参与取最大.
        """
        from cndb.plugins.tables.services.core.ddl import table_exists

        cfg = TextFieldConfig(**(field.config or {}))
        if cfg.default_mode != "auto_increment":
            return None
        fallback = f"{cfg.increment_prefix}{str(cfg.increment_start).zfill(cfg.increment_padding)}"
        if not table_exists(engine, table.db_table_name):
            return fallback

        prefix_re = re.compile(re.escape(cfg.increment_prefix) + r"(\d+)")
        max_seen: int | None = None
        sql = text(
            f'SELECT "{field.db_column_name}" FROM "{table.db_table_name}" WHERE "{field.db_column_name}" IS NOT NULL'  # nosec B608 - 标识符来自内部字段元数据
        )
        with engine.connect() as conn:
            for (value,) in conn.execute(sql):
                m = prefix_re.fullmatch(str(value))
                if m:
                    num = int(m.group(1))
                    if max_seen is None or num > max_seen:
                        max_seen = num
        for value in extra_seen:
            m = prefix_re.fullmatch(str(value))
            if m:
                num = int(m.group(1))
                if max_seen is None or num > max_seen:
                    max_seen = num
        next_num = max(max_seen + 1 if max_seen is not None else cfg.increment_start, cfg.increment_start)
        return f"{cfg.increment_prefix}{str(next_num).zfill(cfg.increment_padding)}"


class LongTextFieldType(FieldType):
    name = "longtext"
    label = "多行文本"
    category = FieldTypeCategory.BASIC
    sqlalchemy_type = Text
    sqlalchemy_length = None


# ── email ──────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


class EmailFieldType(FieldType):
    name = "email"
    label = "邮箱"
    category = FieldTypeCategory.ADVANCED
    sqlalchemy_type = String
    sqlalchemy_length = 255

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not _EMAIL_RE.match(text):
            raise ValueError(f"邮箱格式无效: {text!r}")
        return text.lower()


# ── url ────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://[\w.-]+(?::\d+)?(?:/[\w./?#=&%+-]*)?$", re.IGNORECASE)


class UrlFieldType(FieldType):
    name = "url"
    label = "链接"
    category = FieldTypeCategory.ADVANCED
    sqlalchemy_type = String
    sqlalchemy_length = 1024

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not _URL_RE.match(text):
            raise ValueError(f"URL 格式无效（需以 http:// 或 https:// 开头）: {text!r}")
        return text


# ── phone ──────────────────────────────────────────

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class PhoneFieldType(FieldType):
    name = "phone"
    label = "手机号"
    category = FieldTypeCategory.ADVANCED
    sqlalchemy_type = String
    sqlalchemy_length = 20

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not _PHONE_RE.match(text):
            raise ValueError(f"手机号格式无效（11 位，1 开头）: {text!r}")
        return text


# ── json ─────────────────────────────────────────────


class JsonFieldType(FieldType):
    """JSON 字段类型 —— 存储任意 JSON 值（Text 列）.

    用于 API 自动建表时遇到的嵌套对象/数组。值在 Python 端是 dict/list/None，
    落库时序列化为 JSON 字符串.
    """

    name = "json"
    label = "JSON"
    category = FieldTypeCategory.ADVANCED
    sqlalchemy_type = Text
    sqlalchemy_length = None
    has_physical_column = True

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        import json

        if value is None or value == "":
            return None
        if isinstance(value, str):
            # 反序列化路径：已是 JSON 字符串，校验格式后原样返回
            try:
                json.loads(value)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"JSON 值格式无效: {value!r}") from exc
            return value
        # 序列化路径：dict / list / 标量 等
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"无法序列化为 JSON: {exc}") from exc

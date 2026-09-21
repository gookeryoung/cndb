from __future__ import annotations

import enum
import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, override

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text, text

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
        from cndb.plugins.tables.ddl import table_exists

        cfg = TextFieldConfig(**(field.config or {}))
        if cfg.default_mode != "auto_increment":
            return None
        fallback = f"{cfg.increment_prefix}{str(cfg.increment_start).zfill(cfg.increment_padding)}"
        if not table_exists(engine, table.db_table_name):
            return fallback

        prefix_re = re.compile(re.escape(cfg.increment_prefix) + r"(\d+)")
        max_seen: int | None = None
        sql = text(
            f'SELECT "{field.db_column_name}" FROM "{table.db_table_name}" WHERE "{field.db_column_name}" IS NOT NULL'
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


class NumberFieldConfig(FieldTypeConfig):
    min: float | None = None
    max: float | None = None
    decimals: int = Field(default=0, ge=0, le=10)


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
        v = float(value)
        if cfg.min is not None and v < cfg.min:
            raise ValueError(f"值 {v} 小于最小值 {cfg.min}")
        if cfg.max is not None and v > cfg.max:
            raise ValueError(f"值 {v} 大于最大值 {cfg.max}")
        return round(v, cfg.decimals)


def _normalize_numeric_string(value: str) -> str | None:
    """把带千分位/货币符号/会计负号/全角符号的数字字符串归一为纯数字串.

    惰性导入 :func:`transfer._normalize_numeric` 打破循环依赖
    （transfer → records/models → field_types），复用推断层同一套归一逻辑，
    保证"识别出的格式一定能转换"。
    """
    from cndb.plugins.tables.transfer import _normalize_numeric

    return _normalize_numeric(value)


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
    def default_value(self, _config: dict[str, Any]) -> bool:
        return False


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


# ── 单选 / 多选 ────────────────────────────────────────


class SelectOption(BaseModel):
    """选项定义 —— 显示标签 + 存储值.

    Attributes:
        label: 前端展示用的标签文本.
        value: 实际存储值（字符串或整数）.
        color: 可选颜色标记（前端用 Tag 展示时使用），空或省略表示不指定.
    """

    label: str
    value: str | int
    color: str = ""

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, v: Any) -> Any:  # pragma: no cover - validator 边界分支
        """把 dict 中可能的 '' 空字符串转成 label（dict 构建场景由调用方填充）."""
        if v in (None, ""):
            return ""
        return v


class SelectFieldConfig(FieldTypeConfig):
    """单选字段配置.

    options 同时接受三种输入形式，最终一律规范化为 SelectOption 列表：
    1. 纯字符串列表 ["男", "女"] —— value=label
    2. 字典列表 [{"label": "男", "value": 1}, ...]
    3. SelectOption 对象列表

    当某个 option 的 color 为空字符串时，规范化阶段会自动调用
    :mod:`smart_color` 模块做语义匹配，填入推荐色名；用户已手动设置的
    color 不会被覆盖。
    """

    options: list[SelectOption] = Field(default_factory=list)
    # 是否在规范化时自动为空白 color 填充语义配色（默认开启）
    auto_fill_colors: bool = True

    @field_validator("options", mode="before")
    @classmethod
    def _normalize_options(cls, v: Any) -> list[SelectOption]:  # pragma: no cover - validator 边界分支
        if v is None:
            return []
        result: list[SelectOption] = []
        raw_labels: list[str] = []  # 收集 label，批量调用 suggest_colors
        empty_color_indices: list[int] = []  # 哪些选项 color 为空

        for i, item in enumerate(v):
            if isinstance(item, SelectOption):
                opt = item
            elif isinstance(item, str):
                opt = SelectOption(label=item, value=item)
            elif isinstance(item, dict):
                label = str(item.get("label", ""))
                val = item.get("value", label)
                opt = SelectOption(label=label, value=val, color=str(item.get("color", "")))
            else:
                raise ValueError(f"options 每项必须是 str / dict / SelectOption，收到 {type(item)!r}")

            result.append(opt)
            raw_labels.append(opt.label)
            if not opt.color:
                empty_color_indices.append(i)

        # 空 options 合法（允许导入后自动补全），跳过智能配色
        if not result:
            return result

        # 批量智能配色：仅填充空白 color
        if empty_color_indices:
            from .smart_color import suggest_colors

            all_colors = suggest_colors(raw_labels)
            for idx in empty_color_indices:
                if not result[idx].color:
                    result[idx] = SelectOption(
                        label=result[idx].label,
                        value=result[idx].value,
                        color=all_colors[idx],
                    )

        return result

    def option_values(self) -> list[str]:
        """返回所有选项的 value 列表（用于校验）."""
        return [str(opt.value) for opt in self.options]

    def apply_smart_colors(self, *, overwrite: bool = False) -> None:
        """显式对当前选项列表应用智能配色.

        Args:
            overwrite: 是否覆盖已手动设置的 color。False（默认）仅填充空白项；
                True 时全部重新配色，用于前端"一键智能配色"按钮场景。
        """
        from .smart_color import suggest_colors

        labels = [opt.label for opt in self.options]
        colors = suggest_colors(labels)
        for i, opt in enumerate(self.options):
            if overwrite or not opt.color:
                self.options[i] = SelectOption(
                    label=opt.label,
                    value=opt.value,
                    color=colors[i],
                )


class SelectFieldType(FieldType):
    name = "select"
    label = "单选"
    category = FieldTypeCategory.SELECT
    sqlalchemy_type = String
    sqlalchemy_length = 255
    config_schema = SelectFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        cfg = SelectFieldConfig(**_config)
        # options 为空时放行（导入前预填充 options 前的过渡期）
        if not cfg.options:
            return str(value)
        allowed = cfg.option_values()
        str_val = str(value)
        if str_val not in allowed:
            raise ValueError(f"{value!r} 不在可选值 {allowed} 中")
        return str_val


class MultiSelectFieldConfig(SelectFieldConfig):
    pass


# multiselect 字符串值的分隔符：半/全角逗号、半/全角分号、顿号
# （validate 拆分、field_ops options 预填充/同步、transfer 推断层列表识别三处共用，
# 测试矩阵双向锁定）
MULTI_SELECT_SPLIT_RE = re.compile(r"[,，;；、]")


def split_multi_select_string(value: str) -> list[str]:
    """把 multiselect 字符串值按分隔符拆分为选项列表（去空白项）.

    validate_value 拆分存储值、field_ops 预填充/同步 options、transfer
    推断层列表识别三处共用，保证分隔符语义一致。
    """
    return [p.strip() for p in MULTI_SELECT_SPLIT_RE.split(value) if p.strip()]


class MultiSelectFieldType(FieldType):
    name = "multiselect"
    label = "多选"
    category = FieldTypeCategory.SELECT
    sqlalchemy_type = Text
    sqlalchemy_length = None
    config_schema = MultiSelectFieldConfig

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        if value is None:
            return None
        cfg = MultiSelectFieldConfig(**_config)
        # options 为空时放行（导入前预填充 options 前的过渡期）
        if isinstance(value, list):
            values = value
        elif isinstance(value, str):
            # 字符串按分隔符拆分为多值（与推断层列表识别、options 预填充共用同一分隔符集）
            values = split_multi_select_string(value)
        else:
            values = [value]
        result: list[str] = []
        if cfg.options:
            allowed = cfg.option_values()
            for v in values:
                str_v = str(v)
                if str_v not in allowed:
                    raise ValueError(f"{v!r} 不在可选值 {allowed} 中")
                result.append(str_v)
        else:
            for v in values:
                result.append(str(v))
        return ",".join(result)


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


# ── 字段类型别名归一化 ─────────────────────────────────

# 历史别名 → 后端 registry 真实名（向前兼容前端旧数据和存量记录）
_FIELD_TYPE_ALIASES: dict[str, str] = {
    # 前端旧名 / Django 时代名 → FastAPI 后端名
    "decimal": "float",
    "long_text": "longtext",
    "multi_select": "multiselect",
    "integer": "number",
    "checkbox": "boolean",
    "single_select": "select",
    "multi": "multiselect",
    # 大小写宽容
    "LongText": "longtext",
    "MultiSelect": "multiselect",
}


def normalize_field_type(name: str) -> str:
    """把前端传来的字段类型名归一化为后端 registry 注册的真实名.

    未知别名原样返回（由下游 registry.get 处理）。
    """
    if not isinstance(name, str):
        return str(name)
    # 先查别名表
    alias = _FIELD_TYPE_ALIASES.get(name)
    if alias is not None:
        return alias
    # 再尝试大小写不敏感匹配
    lower = name.lower()
    if lower != name:
        alias_ci = _FIELD_TYPE_ALIASES.get(lower)
        if alias_ci is not None:
            return alias_ci
    return name


class FieldTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, FieldType] = {}

    def register(self, ft: FieldType) -> FieldType:
        if isinstance(ft, type):
            ft = ft()
        if not ft.name:
            raise ValueError("FieldType 必须定义 name")
        self._types[ft.name] = ft
        return ft

    def get(self, name: str) -> FieldType | None:
        # 自动归一化字段类型别名
        return self._types.get(normalize_field_type(name))

    def all(self) -> list[FieldType]:
        return list(self._types.values())

    def choices(self) -> list[tuple[str, str]]:
        return [(ft.name, ft.label) for ft in self._types.values()]

    def unregister(self, name: str) -> None:
        """移除已注册的字段类型（供测试或插件卸载使用）."""
        self._types.pop(name, None)


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


# ── attachment ──────────────────────────────────────


class AttachmentFieldConfig(FieldTypeConfig):
    """附件字段的字段级配置.

    Attributes:
        max_size_mb: 单个附件最大 MB 数，0 表示由后端全局限制.
        allowed_mime_types: 允许的 MIME 类型白名单；空列表表示不限制.
        multiple: 是否允许多文件.
    """

    max_size_mb: int = Field(default=10, ge=0, le=1024)
    allowed_mime_types: list[str] = Field(default_factory=list)
    multiple: bool = True


class AttachmentFieldType(FieldType):
    """附件字段类型 —— 存储上传后返回的元数据列表（JSON 数组 in Text 列）.

    存储模型：值是 JSON 数组，每项形如::

        {
            "file_key":      "uuid.ext",     # 上传接口返回的稳定存储键
            "filename":      "report.pdf",    # 原始文件名
            "size":          12345,           # 字节数
            "mime_type":     "application/pdf",
            "created_at":    "2026-09-12T..."
        }

    has_physical_column=True —— 源表上占一个 Text 列存 JSON.
    """

    name = "attachment"
    label = "附件"
    category = FieldTypeCategory.ADVANCED
    sqlalchemy_type = Text
    sqlalchemy_length = None
    config_schema = AttachmentFieldConfig
    has_physical_column = True

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        """校验附件列表并序列化为 JSON 字符串.

        入参可以是：
        - None / [] → 存空数组 JSON
        - list[dict] → 每项必须包含 file_key + filename，可选 size/mime_type
        """
        import json

        if value is None or value == "":
            return None
        if isinstance(value, str):
            # 后端反序列化路径：已经是 JSON 字符串，校验格式后原样返回
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"附件值不是合法的 JSON 数组: {value!r}") from exc
            return value
        if not isinstance(value, list):
            raise ValueError(f"attachment 字段必须是附件元数据列表，收到 {type(value)!r}")

        result: list[dict[str, Any]] = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"附件列表第 {i} 项必须是 dict，收到 {type(item)!r}")
            if not item.get("file_key"):
                raise ValueError(f"附件列表第 {i} 项缺少 file_key")
            if not item.get("filename"):
                raise ValueError(f"附件列表第 {i} 项缺少 filename")
            entry: dict[str, Any] = {
                "file_key": str(item["file_key"]),
                "filename": str(item["filename"]),
            }
            if "size" in item and item["size"] is not None:
                entry["size"] = int(item["size"])
            if "mime_type" in item and item["mime_type"] is not None:
                entry["mime_type"] = str(item["mime_type"])
            if "created_at" in item and item["created_at"] is not None:
                entry["created_at"] = str(item["created_at"])
            result.append(entry)
        return json.dumps(result, ensure_ascii=False)


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


def build_default_registry() -> FieldTypeRegistry:
    reg = FieldTypeRegistry()
    reg.register(TextFieldType())
    reg.register(LongTextFieldType())
    reg.register(NumberFieldType())
    reg.register(FloatFieldType())
    reg.register(BooleanFieldType())
    reg.register(DateFieldType())
    reg.register(DateTimeFieldType())
    reg.register(SelectFieldType())
    reg.register(MultiSelectFieldType())
    reg.register(EmailFieldType())
    reg.register(UrlFieldType())
    reg.register(PhoneFieldType())
    reg.register(PercentageFieldType())
    reg.register(TimestampFieldType())
    reg.register(LinkFieldType())
    reg.register(AttachmentFieldType())
    reg.register(JsonFieldType())
    return reg


default_registry = build_default_registry()

__all__ = [
    "AttachmentFieldConfig",
    "AttachmentFieldType",
    "BooleanFieldType",
    "DateFieldConfig",
    "DateFieldType",
    "DateTimeFieldType",
    "EmailFieldType",
    "FieldType",
    "FieldTypeCategory",
    "FieldTypeConfig",
    "FieldTypeRegistry",
    "FloatFieldType",
    "LinkFieldConfig",
    "LinkFieldType",
    "LongTextFieldType",
    "MultiSelectFieldConfig",
    "MultiSelectFieldType",
    "NumberFieldConfig",
    "NumberFieldType",
    "PercentageFieldConfig",
    "PercentageFieldType",
    "PhoneFieldType",
    "SelectFieldConfig",
    "SelectFieldType",
    "SelectOption",
    "TextFieldConfig",
    "TextFieldType",
    "TimestampFieldType",
    "UrlFieldType",
    "build_default_registry",
    "default_registry",
]

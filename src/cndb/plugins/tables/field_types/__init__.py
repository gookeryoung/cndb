from __future__ import annotations

import enum
import re
from typing import Any, override

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text


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


class TextFieldType(FieldType):
    name = "text"
    label = "单行文本"
    category = FieldTypeCategory.BASIC
    sqlalchemy_type = String
    sqlalchemy_length = 255


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
        cfg = NumberFieldConfig(**_config)
        v = int(value)
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
        cfg = NumberFieldConfig(**_config)
        v = float(value)
        if cfg.min is not None and v < cfg.min:
            raise ValueError(f"值 {v} 小于最小值 {cfg.min}")
        if cfg.max is not None and v > cfg.max:
            raise ValueError(f"值 {v} 大于最大值 {cfg.max}")
        return round(v, cfg.decimals)


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
            return value.lower() in ("true", "yes", "1", "on")
        raise ValueError(f"无法将 {value!r} 转为布尔值")

    @override
    def default_value(self, _config: dict[str, Any]) -> bool:
        return False


# ── 日期字段（含自动填充）─────────────────────────────────


class DateFieldConfig(FieldTypeConfig):
    """日期/日期时间字段的可配置项.

    Attributes:
        include_time: 是否包含时间部分（仅 date 类型使用）.
        auto_fill: 自动填充时机。空字符串表示不自动填充，"on_create" 表示创建时填入当前时间，
            "on_update" 表示每次更新都覆盖为当前时间（适合"更新时间"戳）.
    """

    include_time: bool = False
    auto_fill: str = Field(default="", pattern=r"^(on_create|on_update)?$")

    def should_auto_fill(self, *, for_update: bool) -> bool:  # pragma: no cover - auto_fill 待补测试
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
            for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"日期格式错误: {value}")
        raise ValueError(f"不支持的日期类型: {type(value)}")

    @override
    def default_value(self, _config: dict[str, Any]) -> Any:  # pragma: no cover - auto_fill 待补测试
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
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(value.strip(), fmt)
                except ValueError:
                    continue
            raise ValueError(f"日期时间格式错误: {value}")
        raise ValueError(f"不支持的日期时间类型: {type(value)}")

    @override
    def default_value(self, _config: dict[str, Any]) -> Any:  # pragma: no cover - auto_fill 待补测试
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
    """

    options: list[SelectOption] = Field(default_factory=list)

    @field_validator("options", mode="before")
    @classmethod
    def _normalize_options(cls, v: Any) -> list[SelectOption]:  # pragma: no cover - validator 边界分支
        if v is None:
            return []
        result: list[SelectOption] = []
        for item in v:
            if isinstance(item, SelectOption):
                result.append(item)
            elif isinstance(item, str):
                result.append(SelectOption(label=item, value=item))
            elif isinstance(item, dict):
                label = str(item.get("label", ""))
                val = item.get("value", label)
                result.append(SelectOption(label=label, value=val, color=str(item.get("color", ""))))
            else:
                raise ValueError(f"options 每项必须是 str / dict / SelectOption，收到 {type(item)!r}")
        if not result:
            raise ValueError("options 不能为空")
        return result

    def option_values(self) -> list[str]:
        """返回所有选项的 value 列表（用于校验）."""
        return [str(opt.value) for opt in self.options]


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
        allowed = cfg.option_values()
        str_val = str(value)
        if str_val not in allowed:
            raise ValueError(f"{value!r} 不在可选值 {allowed} 中")
        return str_val


class MultiSelectFieldConfig(SelectFieldConfig):
    pass


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
        allowed = cfg.option_values()
        values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for v in values:
            str_v = str(v)
            if str_v not in allowed:
                raise ValueError(f"{v!r} 不在可选值 {allowed} 中")
            result.append(str_v)
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
    """百分比字段 —— 存储 0.0 ~ 1.0 的浮点数."""

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
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"百分比必须是数字: {value!r}") from exc
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
        if ts < 0 or ts > 4102444800:
            raise ValueError(f"时间戳超出合理范围 (0~4102444800): {ts}")
        return ts


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
    "TextFieldType",
    "TimestampFieldType",
    "UrlFieldType",
    "build_default_registry",
    "default_registry",
]

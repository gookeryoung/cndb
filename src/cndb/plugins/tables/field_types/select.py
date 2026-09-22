"""选择族字段类型 — 单选 / 多选（含选项智能配色与分隔符约定）."""

from __future__ import annotations

import re
from typing import Any, override

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, Text

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig


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

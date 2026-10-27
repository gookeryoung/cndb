"""字段配置的展示序列化 —— select/multiselect 超大 options 截断（ADR 0046 D6）.

「股票代码」这类字段的 options 是**标的清单**（本土库 7,289 项、config ≈ 450KB）。
展示链路（表详情 / 字段列表）不需要全部选项，却要为每次进表付出传输 + JSON 解析成本。

这里只在**序列化层**截断：库内 config 与校验链路（ADR 0035 允许值缓存 / 导入校验 /
字段编辑器）始终拿全量。截断时带 ``options_truncated`` + ``options_total``，
前端据此把 Tag 颜色从「选项位置」切到「值稳定哈希」，并且编辑入口改调 ``?full=1``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cndb.plugins.tables.models import DataField
    from cndb.plugins.tables.schemas import FieldResponse

#: 展示序列化的 options 上限（超过即截断）
OPTIONS_DISPLAY_LIMIT = 500


def truncate_field_config(config: dict[str, Any] | None, *, full: bool = False) -> dict[str, Any] | None:
    """按展示上限截断 ``config.options``；``full=True`` 原样返回（编辑 / 校验链路）."""
    if full or not isinstance(config, dict):
        return config
    options = config.get("options")
    if not isinstance(options, list) or len(options) <= OPTIONS_DISPLAY_LIMIT:
        return config
    truncated = dict(config)
    truncated["options"] = options[:OPTIONS_DISPLAY_LIMIT]
    truncated["options_truncated"] = True
    truncated["options_total"] = len(options)
    return truncated


def field_response(field: DataField, *, full: bool = False) -> FieldResponse:
    """把 DataField 序列化为响应模型，并按需截断 options."""
    from cndb.plugins.tables.schemas import FieldResponse

    response = FieldResponse.model_validate(field, from_attributes=True)
    return response.model_copy(update={"config": truncate_field_config(field.config, full=full) or {}})


__all__ = ["OPTIONS_DISPLAY_LIMIT", "field_response", "truncate_field_config"]

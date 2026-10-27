"""文档图表子模块（ADR 0048）：注册表 + 唯一渲染管线.

对外只暴露渲染组合函数；模板 schema / 归一 / 校验见 ``registry``，
SVG / PNG 写端见 ``svg`` / ``raster``。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.documents.services.charts.raster import to_png
from cndb.plugins.documents.services.charts.registry import (
    CHART_CATEGORIES,
    CHART_TEMPLATES,
    get_template,
    normalize_config,
    require_valid_config,
    template_fingerprint,
    templates_payload,
    validate_config,
)
from cndb.plugins.documents.services.charts.render import (
    BadRequestTemplateError,
    ChartDocument,
    render_chart,
    render_degraded,
)
from cndb.plugins.documents.services.charts.svg import to_svg

__all__ = [
    "CHART_CATEGORIES",
    "CHART_TEMPLATES",
    "BadRequestTemplateError",
    "ChartDocument",
    "get_template",
    "normalize_config",
    "render_chart",
    "render_degraded",
    "render_instance_svg",
    "require_valid_config",
    "template_fingerprint",
    "templates_payload",
    "to_png",
    "to_svg",
    "validate_config",
]


def render_instance_svg(template_key: str, config: Any, chart_id: int) -> str:
    """实例渲染为 SVG 文本（I1 组合入口，成员 render 与游客分享 render 共用）.

    模板下线降级为占位整幅图（边界 3，I5/I6），不抛错。
    """
    try:
        return to_svg(render_chart(template_key, config or {}))
    except BadRequestTemplateError:
        return to_svg(render_degraded(chart_id, "[图表引用无效：模板已下线]"))

"""文档图表子模块（ADR 0048）：注册表 + 唯一渲染管线.

对外只暴露渲染组合函数；模板 schema / 归一 / 校验见 ``registry``，
SVG / PNG 写端见 ``svg`` / ``raster``。
"""

from __future__ import annotations

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
    "require_valid_config",
    "template_fingerprint",
    "templates_payload",
    "to_png",
    "to_svg",
    "validate_config",
]

"""领域模板包 —— 按 provider 预置的「分析模板」套件（ADR 0006 M5）.

用途：同步落表之后，用户不必从零配公式与图表，直接套用对应领域的分析模板
（`POST /analytics/templates` 的 `config` 即可用返回值）。

字段名按 provider 的默认输出命名（`http_json` 输出原样透传，模板按业务字段命名）。
若用户在字段映射里改了名，套用时按实际字段名替换即可 —— 模板本身是**声明式配置**，
不绑定表结构。

窗口函数（M4）在模板里已带上 `partition_by` / `order_by`：天气按 city 分区，按时间升序。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.datasource.schemas import DomainTemplate

_WEATHER_DAILY: dict[str, Any] = {
    "id": "weather_daily",
    "provider": "http_json",
    "name": "天气日趋势",
    "description": "按城市看气温与温差，滑动平均削掉日内噪声",
    "reason": "气温类时序：温差看波动、3 日均线看趋势",
    "formulas": [
        {"key": "diff", "label": "温差", "expr": "round([temp_max] - [temp_min], 1)"},
        {
            # 单城市默认不分区；多城市表把 partition_by 设为 city 即可
            "key": "temp_ma3",
            "label": "气温3日均",
            "expr": "round(ma([temp_avg], 3), 1)",
            "order_by": "day",
        },
    ],
    "chart": {"type": "line", "x": "day", "y": "temp_avg", "series": "city", "title": "气温趋势", "aggregation": "avg"},
    "summary": {
        "group_by": "city",
        "metrics": [
            {"field": "temp_avg", "agg": "avg", "label": "平均气温"},
            {"field": "diff", "agg": "max", "label": "最大温差"},
        ],
        "sort_by": "avg(temp_avg)",
        "sort_order": "desc",
        "top_n": 10,
    },
}

DOMAIN_TEMPLATES: tuple[DomainTemplate, ...] = (DomainTemplate.model_validate(_WEATHER_DAILY),)


def list_domain_templates(provider: str | None = None) -> list[DomainTemplate]:
    """领域模板包列表（可按 provider 过滤；顺序稳定）."""
    if provider:
        return [item for item in DOMAIN_TEMPLATES if item.provider == provider]
    return list(DOMAIN_TEMPLATES)


__all__ = ["DOMAIN_TEMPLATES", "list_domain_templates"]

"""领域模板包 —— 按 provider 预置的「分析模板」套件（ADR 0006 M5）.

用途：同步落表之后，用户不必从零配公式与图表，直接套用对应领域的分析模板
（`POST /analytics/templates` 的 `config` 即可用返回值）。

字段名按各 provider 的默认输出命名（`tencent_kline` → symbol/trade_date/close…，
`rss_atom` → title/link/published_at/source…）。若用户在字段映射里改了名，
套用时按实际字段名替换即可 —— 模板本身是**声明式配置**，不绑定表结构。

窗口函数（M4）在模板里已带上 `partition_by` / `order_by`：股票按 symbol 分区、
新闻按 source 分区、天气按 city 分区，都按时间升序。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.datasource.schemas import DomainTemplate

# 股票日线（tencent_kline 默认列）
_KLINE_TREND: dict[str, Any] = {
    "id": "kline_trend",
    "provider": "tencent_kline",
    "name": "股票日线趋势",
    "description": "收盘价 + 5 日均线 + 日涨跌幅，按股票代码分区、按交易日排序",
    "reason": "多标的时序首选：均线平滑短期波动，涨跌幅看节奏",
    "formulas": [
        {
            "key": "ma5",
            "label": "5日均线",
            "expr": "round(ma([close], 5), 2)",
            "partition_by": "symbol",
            "order_by": "trade_date",
        },
        {
            "key": "chg",
            "label": "日涨跌幅(%)",
            "expr": "round(pct_change([close]) * 100, 2)",
            "partition_by": "symbol",
            "order_by": "trade_date",
        },
    ],
    "chart": {
        "type": "line",
        "x": "trade_date",
        "y": "close",
        "series": "symbol",
        "title": "收盘价趋势",
        "aggregation": "avg",
    },
    "summary": {
        "group_by": "symbol",
        "metrics": [
            {"field": "close", "agg": "avg", "label": "平均收盘"},
            {"field": "close", "agg": "max", "label": "区间最高"},
            {"field": "symbol", "agg": "count", "label": "交易日数"},
        ],
        "sort_by": "avg(close)",
        "sort_order": "desc",
        "top_n": 20,
    },
}

_KLINE_RANGE: dict[str, Any] = {
    "id": "kline_range",
    "provider": "tencent_kline",
    "name": "股票波动与量能",
    "description": "振幅、区间排名与成交量均线，识别放量与异动",
    "reason": "振幅 + 量能是判断异动的常用组合",
    "formulas": [
        {
            "key": "amp",
            "label": "振幅(%)",
            "expr": "round(([high] - [low]) / [low] * 100, 2)",
        },
        {
            "key": "vol_ma5",
            "label": "5日均量",
            "expr": "round(ma([volume], 5), 0)",
            "partition_by": "symbol",
            "order_by": "trade_date",
        },
        {
            "key": "vol_rank",
            "label": "量能排名",
            "expr": "rank([volume])",
            "partition_by": "trade_date",
            "order_by": "volume",
            "order_desc": True,
        },
    ],
    "chart": {
        "type": "bar",
        "x": "trade_date",
        "y": "amp",
        "series": "symbol",
        "title": "振幅分布",
        "aggregation": "avg",
    },
    "summary": {
        "group_by": "symbol",
        "metrics": [
            {"field": "amp", "agg": "avg", "label": "平均振幅"},
            {"field": "volume", "agg": "sum", "label": "累计成交量"},
        ],
        "sort_by": "avg(amp)",
        "sort_order": "desc",
        "top_n": 20,
    },
}

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

_NEWS_DIGEST: dict[str, Any] = {
    "id": "news_digest",
    "provider": "rss_atom",
    "name": "新闻来源产出",
    "description": "按来源统计条数，配合时间列看发布节奏",
    "reason": "新闻类数据没有稳定数值指标，用计数 + 来源分组看产出结构",
    # 新闻表通常只有文本与时间列（time/文本无法参与数值窗口），故不预置公式；
    # 需要「按来源内的第几条」时，可自行加公式 rank([某数值列])。
    "formulas": [],
    "chart": {
        "type": "bar",
        "x": "source",
        "y": "link",
        "series": None,
        "title": "来源产出",
        "aggregation": "count",
    },
    "summary": {
        "group_by": "source",
        "metrics": [{"field": "link", "agg": "count", "label": "条数"}],
        "sort_by": "count(link)",
        "sort_order": "desc",
        "top_n": 10,
    },
}

DOMAIN_TEMPLATES: tuple[DomainTemplate, ...] = (
    DomainTemplate.model_validate(_KLINE_TREND),
    DomainTemplate.model_validate(_KLINE_RANGE),
    DomainTemplate.model_validate(_WEATHER_DAILY),
    DomainTemplate.model_validate(_NEWS_DIGEST),
)


def list_domain_templates(provider: str | None = None) -> list[DomainTemplate]:
    """领域模板包列表（可按 provider 过滤；顺序稳定）."""
    if provider:
        return [item for item in DOMAIN_TEMPLATES if item.provider == provider]
    return list(DOMAIN_TEMPLATES)


__all__ = ["DOMAIN_TEMPLATES", "list_domain_templates"]

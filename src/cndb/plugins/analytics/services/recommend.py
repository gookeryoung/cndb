"""字段画像与智能推荐 —— 确定性纯函数 + 入口 ``build_recommendations``.

设计要点：
- **确定性**：不使用随机数，全部推荐按字段顺序与固定优先级生成，
  同一张表多次调用结果完全一致，便于前端缓存与单测；
- **纯函数**：角色判定、字段画像、公式 / 图表 / 汇总 / 典型示例推荐都不依赖
  DB 与请求上下文，入口 ``build_recommendations`` 只负责取数并组合结果；
- **可校验**：推荐产物的 chart / summary 只引用字段名或示例内的公式 key，
  与 ``services.templates.normalize_config`` 的语义校验口径一致。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.analytics.services.compute import metric_key, scan_rows
from cndb.plugins.tables.models import DataField, DataTable

# 字段画像抽样行数上限（前 N 行；row_count 仍取表总行数）
SAMPLE_LIMIT = 1000
# 推荐公式条数上限
MAX_FORMULAS = 4
# 每个字段的示例值条数上限
MAX_SAMPLE_VALUES = 3
# 维度字段的唯一值上限：超过即视为标识字段，不再推荐分组
MAX_DIMENSION_CARDINALITY = 50

# 字段类型 → 分析角色（角色白名单：metric / dimension / time / identifier / ignored）
METRIC_TYPES = frozenset({"number", "float", "percentage"})
TIME_TYPES = frozenset({"date", "datetime", "timestamp"})
DIMENSION_TYPES = frozenset(
    {
        "text",
        "select",
        "boolean",
        "longtext",
        "email",
        "url",
        "phone",
        "multiselect",
        "lookup",
        "link",
    }
)
IGNORED_TYPES = frozenset({"image", "attachment", "json"})

# registry 类别 → 角色（仅当字段类型不在显式映射里时兜底）
_CATEGORY_ROLES: dict[str, str] = {
    "numeric": "metric",
    "date": "time",
    "basic": "dimension",
    "select": "dimension",
    "link": "dimension",
    "advanced": "ignored",
}

# 名称像标识字段：ID / 编号 / 序号 / 编码（"valid" 这类英文单词不会被误判）
_IDENTIFIER_NAME_RE = re.compile(r"(?:^|[^a-z])id$|编号|序号|编码", re.IGNORECASE)

# 比率公式的业务含义关键词：优先「金额/销售额/收入」÷「数量/产量/人数」
_NUMERATOR_KEYWORDS: tuple[str, ...] = (
    "金额",
    "销售额",
    "收入",
    "营收",
    "利润",
    "成本",
    "费用",
    "单价",
    "价格",
    "总价",
    "预算",
)
_DENOMINATOR_KEYWORDS: tuple[str, ...] = (
    "数量",
    "产量",
    "人数",
    "件数",
    "天数",
    "次数",
    "面积",
    "用量",
    "销量",
    "工时",
)

Role = str


# ── 基础判定 ──────────────────────────────────────────


def _is_blank(value: Any) -> bool:
    """画像口径的空值判定：None / 纯空白字符串 / 空容器视为空."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


def _value_key(value: Any) -> str:
    """去重用的值键：容器序列化为稳定 JSON，其余取 str."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _display_value(value: Any) -> str:
    """示例值展示：布尔中文化，容器转 JSON，其余去空白."""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value).strip()


def _normalized_type(field_type: str) -> str:
    """字段类型归一化（去空白 + 小写）."""
    return (field_type or "").strip().lower()


def _category_role(field_type: str) -> Role | None:
    """用字段类型注册表的 category 兜底推断角色；注册表不可用时返回 None."""
    try:
        from cndb.plugins.tables.field_types.registry import default_registry

        field = default_registry.get(field_type)
    except Exception:  # pragma: no cover - registry 属于核心依赖，仅防御性兜底
        return None
    if field is None:
        return None
    return _CATEGORY_ROLES.get(str(getattr(field.category, "value", field.category)))


def _role_for_type(field_type: str) -> Role:
    """按字段类型给出候选角色（未识别类型回退为 dimension）."""
    ft = _normalized_type(field_type)
    if ft in METRIC_TYPES:
        return "metric"
    if ft in TIME_TYPES:
        return "time"
    if ft in IGNORED_TYPES:
        return "ignored"
    if ft in DIMENSION_TYPES:
        return "dimension"
    return _category_role(ft) or "dimension"


def _looks_like_identifier(name: str) -> bool:
    """字段名是否像标识字段（ID / 编号 / 序号 / 编码）."""
    return bool(_IDENTIFIER_NAME_RE.search(name or ""))


def classify_role(name: str, field_type: str, cardinality: int, sampled_rows: int) -> Role:
    """判定字段在分析中的角色（确定性）.

    Args:
        name: 字段显示名.
        field_type: 字段类型名（number/percentage/date/text/...）.
        cardinality: 抽样数据中该字段的去重非空值数量.
        sampled_rows: 抽样行数（0 表示空表）.

    Returns:
        metric / dimension / time / identifier / ignored 之一.
    """
    role = _role_for_type(field_type)
    if role != "dimension":
        return role
    if _looks_like_identifier(name):
        return "identifier"
    if sampled_rows > 0 and cardinality > MAX_DIMENSION_CARDINALITY:
        return "identifier"
    return "dimension"


def _role_reason(role: Role, field: DataField, cardinality: int) -> str:
    """字段角色 → 中文推荐理由."""
    if role == "metric":
        if _normalized_type(field.field_type) == "percentage":
            return "百分比字段，优先用均值 / 占比分析，直接求和会失真"
        return "数值字段，适合作为求和、平均等指标"
    if role == "time":
        return "日期时间字段，适合按时间维度看趋势"
    if role == "identifier":
        if _looks_like_identifier(field.name):
            return "名称像 ID / 编号，适合作为行标识而不建议分组"
        return f"唯一值较多（{cardinality} 个），更可能是标识字段，不建议分组"
    if role == "ignored":
        return "图片 / 附件 / JSON 结构化字段，不参与常规统计分析"
    return f"类别字段（{cardinality} 个取值），适合作为分组维度"


# ── 字段画像 ──────────────────────────────────────────


def profile_fields(fields: Sequence[DataField], sampled_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """对每个字段做抽样画像并判定角色（输出顺序 = 字段顺序）.

    Args:
        fields: 可见字段（已按展示顺序排序）.
        sampled_rows: 抽样行（``row.get(字段名)`` 取值）.

    Returns:
        每项含 name / field_type / role / reason / cardinality / completeness / sample_values.
    """
    total = len(sampled_rows)
    profiles: list[dict[str, Any]] = []
    for field in fields:
        values = [row.get(field.name) for row in sampled_rows]
        non_empty = [value for value in values if not _is_blank(value)]
        keys = {_value_key(value) for value in non_empty}
        cardinality = len(keys)
        role = classify_role(field.name, field.field_type, cardinality, total)

        sample_values: list[str] = []
        seen: set[str] = set()
        for value in non_empty:
            key = _value_key(value)
            if key in seen:
                continue
            seen.add(key)
            sample_values.append(_display_value(value))
            if len(sample_values) >= MAX_SAMPLE_VALUES:
                break

        profiles.append(
            {
                "name": field.name,
                "field_type": _normalized_type(field.field_type),
                "role": role,
                "reason": _role_reason(role, field, cardinality),
                "cardinality": cardinality,
                "completeness": len(non_empty) / total if total else 0.0,
                "sample_values": sample_values,
            }
        )
    return profiles


def visible_fields(table: DataTable, sampled_rows: Sequence[dict[str, Any]]) -> list[DataField]:
    """该表可见字段（按字段顺序；隐藏字段与扫描不到的行键一律排除）.

    空表时退回全部非隐藏字段，保证仍能按字段类型给出推荐。
    """
    active = [field for field in table.active_fields() if not field.hidden]
    if not sampled_rows:
        return active
    keys: set[str] = set()
    for row in sampled_rows:
        keys.update(row.keys())
    return [field for field in active if field.name in keys]


# ── 公式推荐 ──────────────────────────────────────────


def _ratio_pair(metrics: Sequence[dict[str, Any]]) -> tuple[str, str] | None:
    """挑一对用于比率公式的数值字段：优先业务含义组合，否则取前两个.

    Returns:
        (分子字段, 分母字段)；不足两个数值字段时返回 None.
    """
    if len(metrics) < 2:
        return None
    numerators = [m for m in metrics if any(kw in m["name"] for kw in _NUMERATOR_KEYWORDS)]
    denominators = [m for m in metrics if any(kw in m["name"] for kw in _DENOMINATOR_KEYWORDS)]
    for numerator in numerators:
        for denominator in denominators:
            if numerator["name"] != denominator["name"]:
                return str(numerator["name"]), str(denominator["name"])
    return str(metrics[0]["name"]), str(metrics[1]["name"])


def recommend_formulas(profiles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """按字段角色推荐最多 4 条公式（key 依次为 metric_1、metric_2…）.

    规则：
    - 数值字段合计 ``sum([f])``；
    - 百分比字段均值 ``round(avg([f])*100,2)``（百分比优先均值，不优先求和）；
    - 占比 ``round([f]/sum([f])*100,2)``；
    - 数值对单位比率 ``round([a]/[b],2)``（优先金额类 ÷ 数量类）。
    """
    metrics = [p for p in profiles if p["role"] == "metric"]
    plain = [p for p in metrics if p["field_type"] != "percentage"]
    percentages = [p for p in metrics if p["field_type"] == "percentage"]

    candidates: list[tuple[str, str, str]] = []
    if plain:
        name = str(plain[0]["name"])
        candidates.append((f"{name}合计", f"sum([{name}])", "数值字段求和，用于看整体规模"))
    if percentages:
        name = str(percentages[0]["name"])
        candidates.append(
            (
                f"平均{name}",
                f"round(avg([{name}])*100,2)",
                "百分比字段用均值更稳定，乘 100 便于阅读",
            )
        )
    if plain:
        name = str(plain[0]["name"])
        candidates.append(
            (
                f"{name}占比",
                f"round([{name}]/sum([{name}])*100,2)",
                "单行数值占合计的比例，用于定位主要贡献",
            )
        )
    pair = _ratio_pair(metrics)
    if pair is not None:
        numerator, denominator = pair
        candidates.append(
            (
                f"{numerator}/{denominator}",
                f"round([{numerator}]/[{denominator}],2)",
                "两个数值字段的比率，反映单位效率",
            )
        )

    formulas: list[dict[str, Any]] = []
    seen_expr: set[str] = set()
    for label, expr, reason in candidates:
        if expr in seen_expr:
            continue
        seen_expr.add(expr)
        formulas.append(
            {
                "key": f"metric_{len(formulas) + 1}",
                "label": label,
                "expr": expr,
                "reason": reason,
            }
        )
        if len(formulas) >= MAX_FORMULAS:
            break
    return formulas


# ── 图表 / 汇总推荐 ───────────────────────────────────


def _chart_spec(
    chart_type: str,
    x: str | None = None,
    y: str | None = None,
    *,
    aggregation: str = "sum",
    title: str = "",
) -> dict[str, Any]:
    """构造 ChartSpec 形状的 dict（字段名 / 公式 key 由调用方保证合法）."""
    return {
        "type": chart_type,
        "x": x,
        "y": y,
        "series": None,
        "title": title,
        "aggregation": aggregation,
    }


def _summary_spec(
    group_by: str | None,
    metrics: list[dict[str, Any]],
    *,
    sort_by: str | None = None,
    sort_order: str = "desc",
    top_n: int | None = 10,
) -> dict[str, Any]:
    """构造 SummarySpec 形状的 dict."""
    return {
        "group_by": group_by,
        "metrics": metrics,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "top_n": top_n,
    }


def _metric_spec(field: str, agg: str, label: str = "") -> dict[str, Any]:
    """构造 SummaryMetric 形状的 dict."""
    return {"field": field, "agg": agg, "label": label}


def _primary_metric(profiles: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """挑主指标：优先非百分比数值字段，其次百分比字段."""
    metrics = [p for p in profiles if p["role"] == "metric"]
    for profile in metrics:
        if profile["field_type"] != "percentage":
            return profile
    return metrics[0] if metrics else None


def recommend_chart(profiles: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """按固定优先级推荐图表（返回 {"chart", "reason"}）.

    优先级：维度+数值 → bar；时间+数值 → line；只有数值 → histogram /
    scatter；无数值仅有维度 → 按维度计数的 bar。
    """
    metrics = [p for p in profiles if p["role"] == "metric"]
    dimensions = [p for p in profiles if p["role"] == "dimension"]
    times = [p for p in profiles if p["role"] == "time"]

    if dimensions and metrics:
        dimension = str(dimensions[0]["name"])
        metric = metrics[0]
        metric_name = str(metric["name"])
        aggregation = "avg" if metric["field_type"] == "percentage" else "sum"
        return {
            "chart": _chart_spec(
                "bar",
                dimension,
                metric_name,
                aggregation=aggregation,
                title=f"{dimension}对比{metric_name}",
            ),
            "reason": f"「{dimension}」是低基数维度，「{metric_name}」是数值指标，柱状图适合分类对比",
        }

    if times and metrics:
        time_name = str(times[0]["name"])
        metric = metrics[0]
        metric_name = str(metric["name"])
        return {
            "chart": _chart_spec(
                "line",
                time_name,
                metric_name,
                aggregation="sum",
                title=f"{metric_name}趋势",
            ),
            "reason": f"「{time_name}」是时间字段，「{metric_name}」是数值指标，折线图适合看趋势",
        }

    if len(metrics) >= 2:
        first = str(metrics[0]["name"])
        second = str(metrics[1]["name"])
        return {
            "chart": _chart_spec("scatter", first, second, title=f"{first} vs {second}"),
            "reason": f"只有数值字段且无可分组维度，「{first}」与「{second}」适合用散点图看相关关系",
        }

    if metrics:
        metric_name = str(metrics[0]["name"])
        return {
            "chart": _chart_spec("histogram", metric_name, title=f"{metric_name}分布"),
            "reason": f"表内只有数值字段，直方图适合观察「{metric_name}」的分布形态",
        }

    if dimensions:
        dimension = str(dimensions[0]["name"])
        return {
            "chart": _chart_spec(
                "bar",
                dimension,
                dimension,
                aggregation="count",
                title=f"{dimension}计数",
            ),
            "reason": f"表内没有数值字段，按「{dimension}」计数可看类别分布",
        }

    if profiles:
        field_name = str(profiles[0]["name"])
        return {
            "chart": _chart_spec(
                "bar",
                field_name,
                field_name,
                aggregation="count",
                title=f"{field_name}计数",
            ),
            "reason": "没有适合作为指标或维度的字段，先按字段计数做整体概览",
        }
    return None


def recommend_summary(profiles: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """推荐分组汇总（返回 {"summary", "reason"}）.

    有维度（或时间字段）时按维度分组并给出 sum/avg 指标 + 计数，Top 10 降序；
    无维度但有数值时做全局汇总；都没有则返回 None。
    """
    dimensions = [p for p in profiles if p["role"] == "dimension"]
    times = [p for p in profiles if p["role"] == "time"]
    group = dimensions[0] if dimensions else (times[0] if times else None)
    metric = _primary_metric(profiles)

    if group is not None:
        group_name = str(group["name"])
        metrics: list[dict[str, Any]] = []
        if metric is not None:
            metric_name = str(metric["name"])
            aggregation = "avg" if metric["field_type"] == "percentage" else "sum"
            metrics.append(_metric_spec(metric_name, aggregation))
        metrics.append(_metric_spec(group_name, "count"))
        first = metrics[0]
        sort_by = metric_key(str(first["agg"]), str(first["field"]))
        return {
            "summary": _summary_spec(group_name, metrics, sort_by=sort_by, top_n=10),
            "reason": f"按「{group_name}」分组汇总并取 Top 10，可快速定位主要分组",
        }

    if metric is not None:
        metric_name = str(metric["name"])
        aggregation = "avg" if metric["field_type"] == "percentage" else "sum"
        return {
            "summary": _summary_spec(
                None,
                [_metric_spec(metric_name, aggregation)],
                sort_by=None,
                top_n=None,
            ),
            "reason": f"没有可分组维度，对「{metric_name}」做全局汇总",
        }
    return None


# ── 典型示例 ──────────────────────────────────────────


def _example(
    example_id: str,
    name: str,
    description: str,
    reason: str,
    *,
    formulas: list[dict[str, Any]] | None = None,
    chart: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 RecommendExample 形状的 dict."""
    return {
        "id": example_id,
        "name": name,
        "description": description,
        "formulas": formulas or [],
        "chart": chart,
        "summary": summary,
        "reason": reason,
    }


def build_examples(profiles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """按适用性生成典型示例，最后始终追加「数据概览」保证至少 1 个.

    每个示例的 formulas / chart / summary 均可通过 ``normalize_config`` 语义校验。
    """
    metrics = [p for p in profiles if p["role"] == "metric"]
    dimensions = [p for p in profiles if p["role"] == "dimension"]
    times = [p for p in profiles if p["role"] == "time"]
    plain = [p for p in metrics if p["field_type"] != "percentage"]

    dimension = str(dimensions[0]["name"]) if dimensions else None
    time_field = str(times[0]["name"]) if times else None
    measure = _primary_metric(profiles)
    measure_name = str(measure["name"]) if measure is not None else None
    measure_agg = "avg" if measure is not None and measure["field_type"] == "percentage" else "sum"

    examples: list[dict[str, Any]] = []

    # 1) 分类对比：维度 + 数值
    if dimension and measure_name:
        examples.append(
            _example(
                "category_compare",
                "分类对比",
                f"按「{dimension}」对比「{measure_name}」",
                "维度与数值指标齐全，柱状图 + 分组汇总适合做分类对比",
                chart=_chart_spec(
                    "bar",
                    dimension,
                    measure_name,
                    aggregation=measure_agg,
                    title=f"{dimension}对比{measure_name}",
                ),
                summary=_summary_spec(
                    dimension,
                    [
                        _metric_spec(measure_name, measure_agg),
                        _metric_spec(dimension, "count"),
                    ],
                    sort_by=metric_key(measure_agg, measure_name),
                    top_n=10,
                ),
            )
        )

    # 2) 数值分布：数值字段直方图
    if measure_name:
        examples.append(
            _example(
                "metric_distribution",
                "数值分布",
                f"查看「{measure_name}」的分布形态",
                "数值字段可用直方图观察分布、偏态与异常值",
                chart=_chart_spec("histogram", measure_name, title=f"{measure_name}分布"),
            )
        )

    # 3) 占比构成：维度 + 数值 + 占比公式
    if dimension and measure_name:
        share_source = str(plain[0]["name"]) if plain else measure_name
        examples.append(
            _example(
                "composition",
                "占比构成",
                f"按「{dimension}」看「{share_source}」的占比构成",
                "占比公式 + 饼图可直观看各分类贡献，汇总表给出平均占比",
                formulas=[
                    {
                        "key": "share",
                        "label": f"{share_source}占比(%)",
                        "expr": f"round([{share_source}]/sum([{share_source}])*100,2)",
                    }
                ],
                chart=_chart_spec("pie", dimension, "share", title=f"{dimension}占比构成"),
                summary=_summary_spec(
                    dimension,
                    [
                        _metric_spec("share", "avg", "平均占比"),
                        _metric_spec(dimension, "count"),
                    ],
                    sort_by=metric_key("avg", "share"),
                    top_n=10,
                ),
            )
        )

    # 4) 时间趋势：时间 + 数值
    if time_field and measure_name:
        examples.append(
            _example(
                "trend",
                "时间趋势",
                f"按「{time_field}」观察「{measure_name}」的变化趋势",
                "折线图 + 按时间升序汇总适合看趋势与周期",
                chart=_chart_spec(
                    "line",
                    time_field,
                    measure_name,
                    aggregation=measure_agg,
                    title=f"{measure_name}趋势",
                ),
                summary=_summary_spec(
                    time_field,
                    [
                        _metric_spec(measure_name, measure_agg),
                        _metric_spec(time_field, "count"),
                    ],
                    sort_by=metric_key(measure_agg, measure_name),
                    sort_order="asc",
                    top_n=10,
                ),
            )
        )

    # 5) 比率分析：至少两个数值字段
    pair = _ratio_pair(metrics)
    if pair is not None:
        numerator, denominator = pair
        group_name = dimension or time_field
        metrics_spec: list[dict[str, Any]] = [_metric_spec("ratio", "avg", "平均比率")]
        if group_name:
            metrics_spec.append(_metric_spec(group_name, "count"))
        examples.append(
            _example(
                "ratio",
                "比率分析",
                f"分析「{numerator}」与「{denominator}」的比率关系",
                "两个数值字段适合用散点图看相关关系，比率公式给出单位效率",
                formulas=[
                    {
                        "key": "ratio",
                        "label": f"{numerator}/{denominator}",
                        "expr": f"round([{numerator}]/[{denominator}],2)",
                    }
                ],
                chart=_chart_spec("scatter", numerator, denominator, title=f"{numerator} vs {denominator}"),
                summary=_summary_spec(
                    group_name,
                    metrics_spec,
                    sort_by=metric_key("avg", "ratio") if group_name else None,
                    top_n=10 if group_name else None,
                ),
            )
        )

    # 6) 数据概览：始终提供（无维度无数值时用全局计数兜底）
    overview_group = dimension or time_field
    if overview_group:
        examples.append(
            _example(
                "overview",
                "数据概览",
                "查看数据规模与分组计数",
                "按维度计数可快速了解数据分布与规模",
                chart=_chart_spec(
                    "bar",
                    overview_group,
                    overview_group,
                    aggregation="count",
                    title=f"{overview_group}计数",
                ),
                summary=_summary_spec(
                    overview_group,
                    [_metric_spec(overview_group, "count")],
                    sort_by=metric_key("count", overview_group),
                    top_n=10,
                ),
            )
        )
    elif profiles:
        count_field = str(profiles[0]["name"])
        examples.append(
            _example(
                "overview",
                "数据概览",
                "查看数据总行数",
                "没有适合分组的字段，先按非空值个数做全局计数",
                summary=_summary_spec(None, [_metric_spec(count_field, "count")], sort_by=None, top_n=None),
            )
        )
    else:
        examples.append(
            _example(
                "overview",
                "数据概览",
                "表中暂无可分析字段",
                "请先添加字段或数据后再做分析",
            )
        )
    return examples


# ── 入口 ──────────────────────────────────────────────


def build_recommendations(
    db: Session,
    table: DataTable,
    user: Any,
    *,
    sample_limit: int = SAMPLE_LIMIT,
) -> dict[str, Any]:
    """入口：扫描表数据（复用行级权限 / 字段隐藏），生成完整推荐响应.

    Args:
        db: 数据库会话.
        table: 数据表（调用方已完成工作区与表级权限校验）.
        user: 当前用户（行级权限 / 字段隐藏口径与求值接口一致）.
        sample_limit: 画像抽样行数上限.

    Returns:
        可直接序列化为 ``RecommendationsResponse`` 的 dict.
    """
    rows, total, _ = scan_rows(db, table, user)
    sampled = rows[:sample_limit]
    fields = visible_fields(table, sampled)
    profiles = profile_fields(fields, sampled)
    return {
        "table_id": table.id,
        "row_count": total,
        "sampled_rows": len(sampled),
        "truncated": total > len(sampled),
        "fields": profiles,
        "formulas": recommend_formulas(profiles),
        "chart": recommend_chart(profiles),
        "summary": recommend_summary(profiles),
        "examples": build_examples(profiles),
    }


__all__ = [
    "MAX_DIMENSION_CARDINALITY",
    "MAX_FORMULAS",
    "MAX_SAMPLE_VALUES",
    "SAMPLE_LIMIT",
    "build_examples",
    "build_recommendations",
    "classify_role",
    "profile_fields",
    "recommend_chart",
    "recommend_formulas",
    "recommend_summary",
    "visible_fields",
]

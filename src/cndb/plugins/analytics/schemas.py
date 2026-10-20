"""analytics 插件请求 / 响应模型."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 图表/分组汇总共用的聚合方式白名单（服务层校验，保持 400 语义）
AGG_KINDS: tuple[str, ...] = ("sum", "avg", "count", "min", "max")


class FormulaSpec(BaseModel):
    """单条自定义计算模板公式."""

    key: str = Field(min_length=1, max_length=64, description="结果列键名（英文标识，唯一）")
    label: str = Field(default="", max_length=200, description="展示名（空则用 key）")
    expr: str = Field(min_length=1, max_length=500, description="公式表达式")
    partition_by: str | None = Field(default=None, max_length=200, description="窗口函数分区字段（空 = 全表一个分区）")
    order_by: str | None = Field(default=None, max_length=200, description="窗口函数排序字段（空 = 原始行序）")
    order_desc: bool = Field(default=False, description="窗口排序方向：false 升序 / true 降序")


class ChartSpec(BaseModel):
    """可视化配置（前端 ECharts 消费）."""

    type: str = Field(default="bar", max_length=32, description="bar/line/pie/scatter/histogram/boxplot")
    x: str | None = Field(default=None, max_length=200, description="维度：字段名或公式 key")
    y: str | None = Field(default=None, max_length=200, description="指标：字段名或公式 key")
    series: str | None = Field(default=None, max_length=200, description="可选第二维度（多系列）")
    title: str = Field(default="", max_length=200)
    # 维度聚合方式（bar/line/pie 生效；histogram/boxplot/scatter 忽略）
    aggregation: str = Field(default="sum", description="sum/avg/count/min/max，维度聚合方式")


class SummaryMetric(BaseModel):
    """分组汇总的一个指标：字段名或公式 key + 聚合函数."""

    field: str = Field(min_length=1, max_length=200, description="字段名或公式 key")
    agg: str = Field(default="sum", description="sum/avg/count/min/max")
    label: str = Field(default="", max_length=200, description="展示名（空则自动生成）")


class SummarySpec(BaseModel):
    """分组汇总配置：按维度分组后计算指标，可排序并取 Top N."""

    group_by: str | None = Field(default=None, max_length=200, description="分组字段（空 = 全局合计）")
    metrics: list[SummaryMetric] = Field(default_factory=list)
    sort_by: str | None = Field(default=None, max_length=220, description="排序指标（指标 key 或来源字段/公式）")
    sort_order: str = "desc"
    top_n: int | None = Field(default=None, ge=1, le=1000, description="仅保留前 N 组（空 = 全部）")


class TemplateConfig(BaseModel):
    """模板配置：公式清单 + 可视化 + 分组汇总."""

    formulas: list[FormulaSpec] = Field(default_factory=list)
    chart: ChartSpec | None = None
    summary: SummarySpec | None = None
    fields: list[str] = Field(default_factory=list)
    limit: int = Field(default=1000, ge=1, le=10000)


class TemplateCreate(BaseModel):
    """新建分析模板."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    table_id: int | None = None
    config: TemplateConfig = Field(default_factory=TemplateConfig)


class TemplateUpdate(BaseModel):
    """更新分析模板（None = 不改）."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    table_id: int | None = None
    config: TemplateConfig | None = None


class TemplateResponse(BaseModel):
    """分析模板响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    table_id: int | None
    name: str
    description: str
    config: dict[str, Any]
    created_by_id: int | None
    updated_by_id: int | None
    created_at: Any
    updated_at: Any


class FormulaCheck(BaseModel):
    """公式校验结果项."""

    key: str
    expr: str
    ok: bool
    error: str = ""
    fields: list[str] = Field(default_factory=list)


class ValidateRequest(BaseModel):
    """公式校验请求."""

    table_id: int | None = None
    formulas: list[FormulaSpec] = Field(default_factory=list)


class ValidateResponse(BaseModel):
    """公式校验响应."""

    ok: bool
    results: list[FormulaCheck] = Field(default_factory=list)
    table_fields: list[str] = Field(default_factory=list)


class ComputeRequest(BaseModel):
    """求值请求：按公式计算派生指标列，可选分组汇总."""

    table_id: int
    formulas: list[FormulaSpec] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list, description="需要返回的原始字段；空 = 全部")
    limit: int = Field(default=1000, ge=1, le=10000)
    summary: SummarySpec | None = Field(default=None, description="分组汇总配置（空 = 不汇总）")
    filters: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "扫描范围过滤，语法同列表接口：{field_name, op, value}。时序表建议给"
            "「时间字段 >= 起点」，把扫描面压到区间内（否则受扫描行数上限截断）"
        ),
    )
    filter_logic: str = Field(default="AND", pattern="^(?i)(and|or)$", description="多条件组合方式")


class ColumnStat(BaseModel):
    """一列的描述统计（仅数值列）."""

    key: str
    label: str = ""
    kind: str = "formula"  # formula | field
    count: int = 0
    missing: int = 0
    mean: float | None = None
    stdev: float | None = None
    variance: float | None = None
    min: float | None = None
    max: float | None = None
    range: float | None = None
    q1: float | None = None
    median: float | None = None
    q3: float | None = None
    sum: float | None = None


class SummaryColumn(BaseModel):
    """分组汇总的一列指标元信息."""

    key: str
    label: str
    agg: str
    source: str


class SummaryResult(BaseModel):
    """分组汇总结果（基于全量扫描行，行数受 top_n 限制）."""

    group_by: str | None = None
    group_label: str = "全部"
    columns: list[SummaryColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    group_count: int = 0
    truncated: bool = False


class ComputeResponse(BaseModel):
    """求值响应：行数据 + 列元信息 + 描述统计 + 可选分组汇总."""

    rows: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False
    table_fields: list[str] = Field(default_factory=list)
    columns: list[ColumnStat] = Field(default_factory=list)
    summary: SummaryResult | None = None


# ── 智能推荐 ──────────────────────────────────────────

# 字段在分析中的角色白名单（前端按此分组展示）
FieldRole = Literal["metric", "dimension", "partition_dimension", "time", "identifier", "ignored"]


class FieldRecommendation(BaseModel):
    """单个字段的画像与角色推荐."""

    name: str
    field_type: str
    role: FieldRole
    reason: str = ""
    cardinality: int | None = Field(default=None, description="去重非空值数量（抽样）")
    completeness: float | None = Field(default=None, description="非空值占比（0~1，抽样）")
    sample_values: list[str] = Field(default_factory=list, description="示例值（最多 3 个）")


class FormulaRecommendation(FormulaSpec):
    """推荐公式：在公式定义上补充推荐理由."""

    reason: str = ""


class ChartRecommendation(BaseModel):
    """推荐图表 + 推荐理由."""

    chart: ChartSpec
    reason: str = ""


class SummaryRecommendation(BaseModel):
    """推荐分组汇总 + 推荐理由."""

    summary: SummarySpec
    reason: str = ""


class RecommendExample(BaseModel):
    """典型分析示例：可直接落成模板配置."""

    id: str = Field(min_length=1, max_length=64, description="示例标识（category_compare 等）")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    formulas: list[FormulaSpec] = Field(default_factory=list)
    chart: ChartSpec | None = None
    summary: SummarySpec | None = None
    reason: str = ""


class RecommendationsResponse(BaseModel):
    """字段画像与智能推荐响应."""

    table_id: int
    row_count: int = 0
    sampled_rows: int = 0
    truncated: bool = False
    fields: list[FieldRecommendation] = Field(default_factory=list)
    formulas: list[FormulaRecommendation] = Field(default_factory=list)
    chart: ChartRecommendation | None = None
    summary: SummaryRecommendation | None = None
    examples: list[RecommendExample] = Field(default_factory=list)


class TemplateDuplicateRequest(BaseModel):
    """复制分析模板请求：name 为空 = 自动命名「原名 副本」."""

    name: str | None = Field(default=None, max_length=200)


__all__ = [
    "AGG_KINDS",
    "ChartRecommendation",
    "ChartSpec",
    "ColumnStat",
    "ComputeRequest",
    "ComputeResponse",
    "FieldRecommendation",
    "FieldRole",
    "FormulaCheck",
    "FormulaRecommendation",
    "FormulaSpec",
    "RecommendExample",
    "RecommendationsResponse",
    "SummaryColumn",
    "SummaryMetric",
    "SummaryRecommendation",
    "SummaryResult",
    "SummarySpec",
    "TemplateConfig",
    "TemplateCreate",
    "TemplateDuplicateRequest",
    "TemplateResponse",
    "TemplateUpdate",
    "ValidateRequest",
    "ValidateResponse",
]

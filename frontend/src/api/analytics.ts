/** 数据分析 API — /api/v1/workspaces/{wid}/analytics/*
 *
 * - templates/*：分析模板 CRUD（模板存后端，含公式 / 图表 / 分组汇总配置，跨设备可用）
 * - validate：公式语法与字段引用校验（编辑器实时反馈）
 * - compute：按公式计算派生指标列 + 描述统计 + 可选分组汇总
 */

import api from './client'

/** 聚合方式（图表维度聚合 / 分组汇总共用） */
export type AnalyticsAgg = 'sum' | 'avg' | 'count' | 'min' | 'max'

export type AnalyticsSortOrder = 'asc' | 'desc'

/** 单条自定义计算模板公式 */
export interface AnalyticsFormula {
  /** 结果列键名（英文标识，模板内唯一） */
  key: string
  /** 展示名（空则用 key） */
  label?: string
  /** 公式表达式，如 round([合格数] / [实际产量] * 100, 2) */
  expr: string
  /** 窗口函数分区字段（空 = 全表一个分区）；如 symbol / city */
  partition_by?: string | null
  /** 窗口函数排序字段（空 = 原始行序）；通常是时间列 */
  order_by?: string | null
  /** 窗口排序方向：false 升序（默认）/ true 降序 */
  order_desc?: boolean
}

/** 可视化配置 */
export interface AnalyticsChart {
  /** bar / line / pie / scatter / histogram / boxplot */
  type: string
  /** 维度：字段名或公式 key */
  x?: string | null
  /** 指标：字段名或公式 key */
  y?: string | null
  /** 可选第二维度（多系列） */
  series?: string | null
  title?: string
  /** 维度聚合方式（bar / line / pie 生效；其它类型忽略） */
  aggregation?: AnalyticsAgg
}

/** 分组汇总的一个指标 */
export interface AnalyticsSummaryMetric {
  /** 字段名或公式 key */
  field: string
  agg: AnalyticsAgg
  /** 展示名（空则自动生成「聚合方式(来源)」） */
  label?: string
}

/** 分组汇总配置 */
export interface AnalyticsSummary {
  /** 分组字段（null = 全局合计） */
  group_by?: string | null
  metrics: AnalyticsSummaryMetric[]
  /** 排序指标：指标 key（如 sum(销售额)）或来源字段 / 公式 key */
  sort_by?: string | null
  sort_order?: AnalyticsSortOrder
  /** 仅保留前 N 组（null = 全部） */
  top_n?: number | null
}

/** 模板配置 */
export interface AnalyticsTemplateConfig {
  formulas: AnalyticsFormula[]
  chart?: AnalyticsChart | null
  summary?: AnalyticsSummary | null
  /** 参与分析的原始字段；空 = 全部可见字段 */
  fields?: string[]
  limit?: number
}

/** 分析模板 */
export interface AnalyticsTemplate {
  id: number
  workspace_id: number
  table_id: number | null
  name: string
  description: string
  config: AnalyticsTemplateConfig
  created_by_id?: number | null
  updated_by_id?: number | null
  created_at?: string
  updated_at?: string
}

export interface AnalyticsTemplateCreate {
  name: string
  description?: string
  table_id?: number | null
  config: AnalyticsTemplateConfig
}

export type AnalyticsTemplateUpdate = Partial<AnalyticsTemplateCreate>

/** 单条公式校验结果 */
export interface FormulaCheck {
  key: string
  expr: string
  ok: boolean
  error?: string
  fields?: string[]
}

export interface AnalyticsValidateResponse {
  ok: boolean
  results: FormulaCheck[]
  table_fields: string[]
}

/** 一列的描述统计 */
export interface AnalyticsColumnStat {
  key: string
  label: string
  /** formula | field */
  kind: string
  count: number
  missing: number
  mean?: number | null
  stdev?: number | null
  variance?: number | null
  min?: number | null
  max?: number | null
  range?: number | null
  q1?: number | null
  median?: number | null
  q3?: number | null
  sum?: number | null
}

/** 分组汇总的一列指标元信息 */
export interface AnalyticsSummaryColumn {
  key: string
  label: string
  agg: string
  source: string
}

/** 分组汇总结果 */
export interface AnalyticsSummaryResult {
  group_by: string | null
  group_label: string
  columns: AnalyticsSummaryColumn[]
  rows: Array<Record<string, unknown> & { group: string }>
  group_count: number
  truncated: boolean
}

export interface AnalyticsComputeResponse {
  /** 行数据（含派生指标列）；id 为行 ID */
  rows: Array<Record<string, unknown> & { id: number | string }>
  total: number
  truncated: boolean
  table_fields: string[]
  columns: AnalyticsColumnStat[]
  /** 分组汇总（未配置时为 null） */
  summary?: AnalyticsSummaryResult | null
}

export interface AnalyticsComputeRequest {
  table_id: number
  formulas: AnalyticsFormula[]
  fields?: string[]
  limit?: number
  summary?: AnalyticsSummary | null
}

/** 智能推荐：字段角色 */
export type AnalyticsRecommendationRole = 'metric' | 'dimension' | 'time' | 'identifier' | 'ignored'

/** 智能推荐：字段画像 */
export interface AnalyticsRecommendationField {
  name: string
  field_type: string
  role: AnalyticsRecommendationRole
  /** 角色判定理由（前端 Tooltip 展示） */
  reason: string
  /** 去重后基数（可空） */
  cardinality?: number | null
  /** 非空率 0~1（可空） */
  completeness?: number | null
  /** 示例值（抽样，最多 3 个） */
  sample_values?: string[] | null
}

/** 智能推荐：公式 */
export interface AnalyticsRecommendationFormula {
  key: string
  label: string
  expr: string
  /** 推荐理由 */
  reason: string
}

/** 智能推荐：图表 + 理由 */
export interface AnalyticsRecommendationChart {
  chart: AnalyticsChart
  reason: string
}

/** 智能推荐：分组汇总 + 理由 */
export interface AnalyticsRecommendationSummary {
  summary: AnalyticsSummary
  reason: string
}

/** 智能推荐：典型示例（一键应用整套配置） */
export interface AnalyticsRecommendationExample {
  id: string
  name: string
  description: string
  formulas: AnalyticsFormula[]
  chart?: AnalyticsChart | null
  summary?: AnalyticsSummary | null
  reason: string
}

/** 智能推荐响应 */
export interface AnalyticsRecommendations {
  table_id: number
  row_count: number
  sampled_rows: number
  truncated: boolean
  fields: AnalyticsRecommendationField[]
  formulas: AnalyticsRecommendationFormula[]
  chart: AnalyticsRecommendationChart | null
  summary: AnalyticsRecommendationSummary | null
  examples: AnalyticsRecommendationExample[]
}

/** 复制模板请求体（空 = 默认「原名 副本」） */
export interface AnalyticsTemplateDuplicate {
  name?: string
}

export const analyticsApi = {
  listTemplates: (wid: number | string) =>
    api.get<AnalyticsTemplate[]>(`/v1/workspaces/${wid}/analytics/templates`).then(r => r.data),
  createTemplate: (wid: number | string, data: AnalyticsTemplateCreate) =>
    api.post<AnalyticsTemplate>(`/v1/workspaces/${wid}/analytics/templates`, data).then(r => r.data),
  updateTemplate: (wid: number | string, id: number | string, data: AnalyticsTemplateUpdate) =>
    api.put<AnalyticsTemplate>(`/v1/workspaces/${wid}/analytics/templates/${id}`, data).then(r => r.data),
  removeTemplate: (wid: number | string, id: number | string) =>
    api.delete(`/v1/workspaces/${wid}/analytics/templates/${id}`).then(() => null),
  /** 复制模板（默认「原名 副本」，重名自动递增） */
  duplicateTemplate: (
    wid: number | string,
    id: number | string,
    data?: AnalyticsTemplateDuplicate,
  ) =>
    api
      .post<AnalyticsTemplate>(`/v1/workspaces/${wid}/analytics/templates/${id}/duplicate`, data ?? {})
      .then(r => r.data),
  /** 智能推荐：字段角色 / 公式 / 图表 / 汇总 / 典型示例 */
  recommend: (wid: number | string, tableId: number | string) =>
    api
      .get<AnalyticsRecommendations>(`/v1/workspaces/${wid}/analytics/recommendations`, {
        params: { table_id: tableId },
      })
      .then(r => r.data),
  validate: (wid: number | string, tableId: number | null, formulas: AnalyticsFormula[]) =>
    api.post<AnalyticsValidateResponse>(`/v1/workspaces/${wid}/analytics/validate`, {
      table_id: tableId, formulas,
    }).then(r => r.data),
  compute: (wid: number | string, data: AnalyticsComputeRequest) =>
    api.post<AnalyticsComputeResponse>(`/v1/workspaces/${wid}/analytics/compute`, data).then(r => r.data),
}

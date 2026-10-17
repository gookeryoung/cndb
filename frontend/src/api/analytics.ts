/** 数据分析 API — /api/v1/workspaces/{wid}/analytics/*
 *
 * - templates/*：分析模板 CRUD（模板存后端，含公式与图表配置，跨设备可用）
 * - validate：公式语法与字段引用校验（编辑器实时反馈）
 * - compute：按公式计算派生指标列 + 描述统计
 */

import api from './client'

/** 单条自定义计算模板公式 */
export interface AnalyticsFormula {
  /** 结果列键名（英文标识，模板内唯一） */
  key: string
  /** 展示名（空则用 key） */
  label?: string
  /** 公式表达式，如 round([合格数] / [实际产量] * 100, 2) */
  expr: string
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
}

/** 模板配置 */
export interface AnalyticsTemplateConfig {
  formulas: AnalyticsFormula[]
  group_by?: string | null
  chart?: AnalyticsChart | null
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
  min?: number | null
  q1?: number | null
  median?: number | null
  q3?: number | null
  max?: number | null
  sum?: number | null
}

export interface AnalyticsComputeResponse {
  /** 行数据（含派生指标列）；id 为行 ID */
  rows: Array<Record<string, unknown> & { id: number | string }>
  total: number
  truncated: boolean
  table_fields: string[]
  columns: AnalyticsColumnStat[]
}

export interface AnalyticsComputeRequest {
  table_id: number
  formulas: AnalyticsFormula[]
  fields?: string[]
  limit?: number
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
  validate: (wid: number | string, tableId: number | null, formulas: AnalyticsFormula[]) =>
    api.post<AnalyticsValidateResponse>(`/v1/workspaces/${wid}/analytics/validate`, {
      table_id: tableId, formulas,
    }).then(r => r.data),
  compute: (wid: number | string, data: AnalyticsComputeRequest) =>
    api.post<AnalyticsComputeResponse>(`/v1/workspaces/${wid}/analytics/compute`, data).then(r => r.data),
}

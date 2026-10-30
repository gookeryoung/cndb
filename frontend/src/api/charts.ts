/** 文档图表 API — /api/v1/workspaces/{wid}/charts/*（ADR 0048 / 0052）
 *
 * 两级模板清单 / 图表素材库 CRUD / render-preview（按 template + config 渲染，不落库；
 * 设计器预览与正文内嵌块共用）。渲染产物是 SVG 文本，由 ChartEmbed 内联展示。
 */

import api from './client'

/** 图表类别（一级；二级分类带 parent 指向一级，ADR 0058） */
export interface ChartCategoryInfo {
  key: string
  name: string
  description: string
  /** 二级分类所属一级 key；一级分类无此字段 */
  parent?: string
  /** 一级分类下的二级分类（仅含非空二级，ADR 0058） */
  children?: ChartCategoryInfo[]
}

/** 模板数据列声明（设计器按此生成数据表列） */
export interface ChartRowColumn {
  key: string
  type: 'text' | 'number' | 'number[]'
  label: string
  required?: boolean
}

/** 模板文案字段声明（设计器按此生成 labels 表单） */
export interface ChartLabelField {
  key: string
  label: string
}

/** 模板样式开关声明（设计器按此生成样式表单，需求卡片 0070 C3） */
export interface ChartStyleField {
  key: string
  label: string
}

/** 行结构类型：dual-axis（label+value+growth）| series（label+values[]）| value（label+value）| xy（x+y） */
export type ChartRowKind = 'dual-axis' | 'series' | 'value' | 'xy'

/** 图表模板（二级）：schema + 默认配置 */
export interface ChartTemplateInfo {
  key: string
  category: string
  name: string
  description: string
  row_min: number
  row_max: number
  row_columns: ChartRowColumn[]
  series_min: number
  series_max: number
  row_kind: ChartRowKind
  label_fields: ChartLabelField[]
  style_fields: ChartStyleField[]
  default_config: Record<string, unknown>
}

/** 两级清单载荷（GET /charts/templates） */
export interface ChartTemplatesPayload {
  categories: ChartCategoryInfo[]
  templates: ChartTemplateInfo[]
}

/** 用户图表实例 */
export interface ChartInstance {
  id: number
  workspace_id: number
  title: string
  template_key: string
  /** 按模板归类的类别；模板下线时为 null */
  category: string | null
  config: Record<string, unknown>
  created_by_id: number | null
  updated_by_id: number | null
  created_at: string
  updated_at: string
}

/** 建实例载荷（config 结构随模板 schema，前端不细拆） */
export interface ChartCreatePayload {
  title: string
  template_key: string
  config: Record<string, unknown>
}

export const chartApi = {
  /** 两级清单：类别 → 模板（含 schema 与默认配置） */
  templates: (wid: number | string) =>
    api.get<ChartTemplatesPayload>(`/v1/workspaces/${wid}/charts/templates`).then(r => r.data),

  /** 实例列表（?category= 按模板类别过滤） */
  list: (wid: number | string, category?: string) =>
    api
      .get<{ items: ChartInstance[] }>(`/v1/workspaces/${wid}/charts`, {
        params: category ? { category } : undefined,
      })
      .then(r => r.data),

  /** 实例读 */
  get: (wid: number | string, chartId: number) =>
    api.get<ChartInstance>(`/v1/workspaces/${wid}/charts/${chartId}`).then(r => r.data),

  /** 建实例（editor+）：后端严格校验 config，400 时 detail 带逐条错误 */
  create: (wid: number | string, payload: ChartCreatePayload) =>
    api.post<ChartInstance>(`/v1/workspaces/${wid}/charts`, payload).then(r => r.data),

  /** 全量覆盖（editor+） */
  update: (wid: number | string, chartId: number, payload: ChartCreatePayload) =>
    api.put<ChartInstance>(`/v1/workspaces/${wid}/charts/${chartId}`, payload).then(r => r.data),

  /** 物理删除（editor+）；已插入正文的定义副本不受影响（ADR 0052 D4） */
  remove: (wid: number | string, chartId: number) =>
    api.delete(`/v1/workspaces/${wid}/charts/${chartId}`).then(r => r.data),

  /** 不落库渲染（D5 设计器实时预览 / ADR 0052 正文内嵌块）：template_key + config → SVG 文本 */
  renderPreview: (wid: number | string, templateKey: string, config: Record<string, unknown>) =>
    api
      .post<string>(
        `/v1/workspaces/${wid}/charts/render-preview`,
        { template_key: templateKey, config },
        { responseType: 'text', transformResponse: [(data: string) => data] },
      )
      .then(r => r.data),
}

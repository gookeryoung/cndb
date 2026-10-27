/** 文档图表 API — /api/v1/workspaces/{wid}/charts/*（ADR 0048）
 *
 * 两级模板清单 / 实例 CRUD / render-preview（设计器实时预览，不落库）/
 * render（SVG + ETag 304）。渲染产物是 SVG 文本，由 ChartEmbed 内联展示。
 */

import api from './client'

/** 图表类别（一级：趋势 / 构成 / 对比） */
export interface ChartCategoryInfo {
  key: string
  name: string
  description: string
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
  label_fields: ChartLabelField[]
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

/** 实例渲染的 ETag 记忆：304 时复用上次 SVG 文本，避免重复内联 */
const renderEtagCache = new Map<number, { etag: string; svg: string }>()

/** 从 Cache-Control / ETag 响应头取 ETag（axios 头名小写） */
function etagOf(headers: Record<string, unknown>): string | null {
  const raw = headers.etag ?? headers.ETag
  return typeof raw === 'string' ? raw : null
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

  /** 物理删除（editor+）；正文引用处由预览 / 导出降级 */
  remove: (wid: number | string, chartId: number) =>
    api.delete(`/v1/workspaces/${wid}/charts/${chartId}`).then(r => r.data),

  /** 不落库渲染（D5 设计器实时预览）：template_key + config → SVG 文本 */
  renderPreview: (wid: number | string, templateKey: string, config: Record<string, unknown>) =>
    api
      .post<string>(
        `/v1/workspaces/${wid}/charts/render-preview`,
        { template_key: templateKey, config },
        { responseType: 'text', transformResponse: [(data: string) => data] },
      )
      .then(r => r.data),

  /** 实例渲染（成员）：SVG 文本；带 ETag 记忆，命中 304 复用上次产物 */
  renderSvg: (wid: number | string, chartId: number) =>
    api
      .get<string>(`/v1/workspaces/${wid}/charts/${chartId}/render`, {
        responseType: 'text',
        transformResponse: [(data: string) => data],
        validateStatus: s => (s >= 200 && s < 300) || s === 304,
        headers: renderEtagCache.get(chartId)
          ? { 'If-None-Match': renderEtagCache.get(chartId)!.etag }
          : undefined,
      })
      .then(r => {
        if (r.status === 304) {
          const cached = renderEtagCache.get(chartId)
          if (cached) return cached.svg
        }
        const etag = etagOf(r.headers as Record<string, unknown>)
        if (etag) renderEtagCache.set(chartId, { etag, svg: r.data })
        return r.data
      }),
}

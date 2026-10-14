/** 报告模板、参数与渲染. */

import type { ID } from './common'

export interface ReportParameter {
  name: string
  type: 'string' | 'number' | 'date' | 'boolean'
  default?: unknown
  required?: boolean
  label?: string
  /** 可选值列表：非空时渲染参数弹窗渲染下拉菜单 */
  options?: string[]
}

/** 报告主题风格取值（与后端 ThemeStyle 对齐） */
export type ReportTheme = 'business' | 'minimal' | 'modern' | 'engineering' | 'academic'

/** 报告模板（列表精简） */
export interface ReportTemplateSummary {
  id: ID
  table_id: number | null
  /** 可选绑定的主表视图 ID：渲染时按视图 filters/sortings 取数；null=取全表数据 */
  view_id: number | null
  /** 归属工作区（显式优先，其次由 table 反推；皆无为 null——不归属任何工作区） */
  workspace_id: number | null
  name: string
  description: string
  output_format: string
  parameters: ReportParameter[]
  /** 持久化的额外引用表 ID 列表（不含主表自身） */
  extra_table_ids: number[]
  /** 主题风格，默认简约 */
  theme: ReportTheme
}

/** 报告模板（详情，含模板内容） */
export interface ReportTemplate extends ReportTemplateSummary {
  template_content: string
  created_at: string
  updated_at: string
}

export interface ReportTemplateCreate {
  name: string
  description?: string
  output_format?: string
  template_content: string
  table_id?: number | null
  /** 可选绑定的主表视图 ID：渲染时按视图 filters/sortings 取数 */
  view_id?: number | null
  /** 归属工作区：显式优先（不存在 404）；未传且 table_id 存在时由表反推；皆无落 null */
  workspace_id?: number | null
  parameters?: ReportParameter[]
  extra_table_ids?: number[]
  theme?: ReportTheme
}

export interface ReportTemplateUpdate {
  name?: string
  description?: string
  output_format?: string
  template_content?: string
  table_id?: number | null
  view_id?: number | null
  parameters?: ReportParameter[]
  extra_table_ids?: number[]
  theme?: ReportTheme
}

export interface ReportRenderRequest {
  table_id: number
  params?: Record<string, unknown>
  row_ids?: Array<number | null> | null
  /** 可选：临时覆盖模板绑定的视图（按视图 filters/sortings 取数） */
  view_id?: number | null
  /** 可选：额外引用的数据表 ID 列表 */
  extra_table_ids?: number[]
}

export interface ReportRenderResult {
  filename: string
  content_type: string
  size: number
}

/** 导入任务状态 */

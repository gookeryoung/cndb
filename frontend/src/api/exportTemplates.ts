/** 导出模板 API — `/api/v1/workspaces/{wid}/documents/templates`（ADR 0152）.
 *
 * 模板是**工作区级**资源：内置预设（research / techreport / … 共 6 套）只读、来自代码常量，
 * 自定义模板落库并与工作区备份一同往返。导出 docx / pdf 时按
 * 「显式 ref → 工作区默认 → 内置 research（研究报告）」解析（后端唯一入口）。
 *
 * UI 入口：个人设置 → 模板（`frontend/src/pages/settings/TemplatePanel.tsx`）与顶栏图标。
 */

import api from './client'

/** 纸张 */
export type TemplatePaper = 'A4' | 'A3' | 'Letter'
/** 对齐 */
export type TemplateAlign = 'left' | 'center' | 'right' | 'justify'
/** 行距规则：倍数 / 固定磅值 */
export type TemplateLineRule = 'multiple' | 'fixed'
/** 页脚页码样式 */
export type TemplatePageNumber = 'none' | 'plain' | 'page' | 'page_of_total'
/** 标题自动编号方案 */
export type TemplateHeadingNumbering = 'none' | 'arabic_multilevel' | 'chapter_chinese' | 'cn_ordinal'
/** 表格样式：全网格 / 三线表 */
export type TemplateTableStyle = 'single' | 'three_line'
/** 列表项目符号 */
export type TemplateListMarker = 'bullet' | 'dash' | 'dot'

export interface TemplatePage {
  paper: TemplatePaper
  margin_top: number
  margin_bottom: number
  margin_left: number
  margin_right: number
}

export interface TemplateHeaderFooter {
  header_text: string
  page_number: TemplatePageNumber
  first_page_different: boolean
  font_size: number
}

export interface TemplateBody {
  latin_font: string
  east_asia_font: string
  size: number
  bold: boolean
  color: string
  align: TemplateAlign
  line_spacing_rule: TemplateLineRule
  line_spacing: number
  line_spacing_pt: number
  space_before: number
  space_after: number
  first_line_indent_chars: number
  char_spacing: number
  widow_control: boolean
  keep_with_next: boolean
}

export interface TemplateHeading {
  latin_font: string
  east_asia_font: string
  size: number
  bold: boolean
  color: string
  align: TemplateAlign
  space_before: number
  space_after: number
  first_line_indent_chars: number
  keep_with_next: boolean
}

export interface TemplateTable {
  style: TemplateTableStyle
  header_bg: string
  header_color: string
  header_bold: boolean
  latin_font: string
  east_asia_font: string
  size: number
  border_color: string
  header_repeat: boolean
  zebra: boolean
  cell_valign: 'top' | 'center'
}

export interface TemplateCaptionStyle {
  enabled: boolean
  position: 'above' | 'below'
  numbering: 'n' | 'n-n'
  size: number
  align: 'left' | 'center' | 'right'
}

export interface TemplateCaptions {
  figure: TemplateCaptionStyle
  table: TemplateCaptionStyle
}

export interface TemplateList {
  indent_pt: number
  hanging_pt: number
  space_after: number
  marker: TemplateListMarker
}

export interface TemplateCode {
  latin_font: string
  east_asia_font: string
  size: number
  bg: string
  border: string
  left_bar: boolean
}

/** 一份导出模板的完整排版（与后端 `ExportTemplateConfig` 逐字段对应） */
export interface ExportTemplateConfig {
  page: TemplatePage
  header_footer: TemplateHeaderFooter
  body: TemplateBody
  headings: TemplateHeading[]
  numbering: { heading: TemplateHeadingNumbering }
  table: TemplateTable
  captions: TemplateCaptions
  lists: TemplateList
  code: TemplateCode
}

/** 模板列表项：内置（source=builtin）或工作区自定义（source=custom） */
export interface ExportTemplateItem {
  /** `builtin:<key>` 或数字 id 的字符串形式 */
  ref: string
  name: string
  description: string
  source: 'builtin' | 'custom'
  is_default: boolean
  config: ExportTemplateConfig
  updated_at: string | null
}

export interface ExportTemplateList {
  items: ExportTemplateItem[]
  /** 当前工作区实际生效的默认模板引用（未设默认即 `builtin:research`，研究报告） */
  default_ref: string
}

export interface ExportTemplateCreatePayload {
  name: string
  description?: string
  /** 从内置预设另存为 */
  preset_key?: string
  /** 或直接提交完整配置 */
  config?: ExportTemplateConfig
}

export interface ExportTemplateUpdatePayload {
  name?: string
  description?: string
  config?: ExportTemplateConfig
  is_default?: boolean
}

export interface ExportTemplateDeleteResult {
  deleted: boolean
  default_ref: string
  was_default: boolean
}

export type ExportTemplatePreviewFormat = 'docx' | 'pdf'

const base = (wid: number | string) => `/v1/workspaces/${wid}/documents/templates`

export const exportTemplateApi = {
  list: (wid: number | string) => api.get<ExportTemplateList>(base(wid)).then(r => r.data),
  get: (wid: number | string, ref: string) =>
    api.get<ExportTemplateItem>(`${base(wid)}/${encodeURIComponent(ref)}`).then(r => r.data),
  create: (wid: number | string, payload: ExportTemplateCreatePayload) =>
    api.post<ExportTemplateItem>(base(wid), payload).then(r => r.data),
  update: (wid: number | string, id: number, payload: ExportTemplateUpdatePayload) =>
    api.put<ExportTemplateItem>(`${base(wid)}/${id}`, payload).then(r => r.data),
  remove: (wid: number | string, id: number) =>
    api.delete<ExportTemplateDeleteResult>(`${base(wid)}/${id}`).then(r => r.data),
  /** 用未保存配置（或已存在模板）渲染示例件，不落库 */
  preview: (
    wid: number | string,
    payload: { config?: ExportTemplateConfig; ref?: string },
    format: ExportTemplatePreviewFormat,
  ) =>
    api
      .post<Blob>(`${base(wid)}/preview`, payload, {
        params: { format },
        responseType: 'blob',
      })
      .then(r => r.data),
}

/** 例：内置 key → 中文名（前端提示与快捷菜单用，真实名称由接口返回） */
export const BUILTIN_TEMPLATE_LABELS: Record<string, string> = {
  research: '研究报告',
  techreport: '技术报告',
  trend: '趋势分析',
  thesis: '论文',
  official: '公文',
  press: '宣传报道',
}

/** 文件分析 / 导入结果与公开分享. */

import type { ID } from './common'
import type { RowResponse } from './records'
import type { TableDetail } from './tables'

export interface FileAnalyzeResult {
  columns: Array<{ name: string; field_type: string; sample_values?: string[]; null_ratio?: number; options?: string[] }>
  total_rows: number
  format: string
  filename?: string
  /** 前端做"典型数据 + 实时转换预览"使用（前 50 行） */
  sample_rows?: Array<Record<string, unknown>>
}
/** 通用文件建表导入结果（新） */
export interface FileImportResult {
  table_id: ID
  table_name: string
  imported_rows: number
  field_count: number
  format?: string
  columns?: Array<{ name: string; field_type: string }>
}

export interface SharedGrid {
  slug: string; title: string; table: TableDetail
  rows: RowResponse[]; total: number
}

/** 报告模板参数定义 */

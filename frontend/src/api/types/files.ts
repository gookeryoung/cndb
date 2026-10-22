/** 文件分析 / 导入结果. */

import type { ID } from './common'

/** 表头行识别候选（按置信度从高到低，最多 5 个）. */
export interface HeaderDetectionCandidate {
  /** 1-based 行号（按文件中的非空行序号；无空行时等于 Excel 行号） */
  row: number
  /** 0~1 概率 */
  confidence: number
  /** 该行前几个单元格的文本预览（已截断） */
  values: string[]
}

/** 后端对 CSV / TSV / XLSX 的表头行自动识别结果（JSON 无表头概念，为 null）. */
export interface HeaderDetection {
  /** 最终采用/识别的表头行（1-based） */
  row: number
  /** 识别结果概率 0~1 */
  confidence: number
  /** 是否建议人工确认（置信度偏低时为 true） */
  requires_review: boolean
  /** 已跳过的上方行数（标题/合并行） */
  skipped_rows: number
  /** 面向用户的中文提示，例如「已自动识别第 2 行为表头（置信度 93%，已跳过上方 1 行标题/合并行）」 */
  message: string
  /** 候选表头行（按置信度从高到低，最多 5 个），用于下拉改选 */
  candidates: HeaderDetectionCandidate[]
}

export interface FileAnalyzeResult {
  columns: Array<{ name: string; field_type: string; sample_values?: string[]; null_ratio?: number; options?: string[] }>
  total_rows: number
  format: string
  filename?: string
  /** 前端做"典型数据 + 实时转换预览"使用（前 50 行） */
  sample_rows?: Array<Record<string, unknown>>
  /** 表头行自动识别结果；JSON 格式为 null */
  header_detection?: HeaderDetection | null
  /** 本次分析实际使用的表头行（1-based）；JSON 格式为 null */
  header_row?: number | null
}
/** 通用文件建表导入结果（新） */
export interface FileImportResult {
  table_id: ID
  table_name: string
  imported_rows: number
  field_count: number
  format?: string
  columns?: Array<{ name: string; field_type: string }>
  /** 实际建表使用的表头行识别结果；JSON 格式为 null */
  header_detection?: HeaderDetection | null
}

/** 报告模板参数定义 */

/** 异步导入任务、校验报告与表级权限. */

import type { ID } from './common'
import type { HeaderDetection } from './files'

export type ImportTaskStatus =
  | 'pending'
  | 'pending_validation'
  | 'pending_confirm'
  | 'running'
  | 'done'
  | 'failed'

/** 校验报告（DiffReporter 输出结构 — V2 支持 upsert + 字段自动新增） */
export interface ValidationReport {
  total: number
  valid_count: number
  warning_count: number
  error_count: number
  /** 表头行自动识别结果；JSON 格式为 null */
  header_detection?: HeaderDetection | null
  /** 本次校验实际使用的表头行（1-based）；JSON 格式为 null */
  header_row?: number | null
  /** V2: 待新增行数（未指定 match_keys 时等于 valid_count） */
  new_count?: number
  /** V2: 待更新行数 */
  update_count?: number
  /** V2: 多行同 key 冲突数 */
  multi_key_conflicts?: number
  skipped_columns: string[]
  missing_required: string[]
  /** V2: 未知列自动新增规划 */
  planned_columns?: Array<{
    name: string; field_type: string; options?: string[]; sample_values?: string[]
  }>
  /** V2: 待新增行预览（限前 200 行） */
  new_preview?: Array<{
    row_number: number; match_key_values: Record<string, unknown>; field_sample: Record<string, unknown>
  }>
  /** V2: 待更新行预览（含字段级 diff） */
  update_preview?: Array<{
    row_number: number; match_key_values: Record<string, unknown>; existing_row_id: number; field_sample: Record<string, unknown>;
    /** 仅包含 changed=true 的业务字段（不含 match_keys）— old 为 DB 旧值, new 为文件新值 */
    field_diffs?: Record<string, { old: unknown; new: unknown; changed: boolean }>
  }>
  warnings: Array<{ row_number: number; field: string; message: string }>
  errors: Array<{ row_number: number; field: string; message: string }>
  actually_imported?: number
  /** V2: execute 后补充 */
  actually_created?: number
  actually_updated?: number
  /** V2: 列级数据质量画像 */
  column_profiles?: Array<{
    name: string
    inferred_type: string
    confidence: number
    fallback_type?: string | null
    null_count: number
    null_ratio: number
    unique_count: number
    sample_values?: string[]
    type_conflicts?: Array<{ row_number: number; value: string; conflicting_type: string }>
    outliers?: Array<{ value: string | number; type: string; row_number?: number | null }>
    /** 数值列: min/max/mean/std */
    min?: number; max?: number; mean?: number; std?: number
    /** 数值列直方图 */
    distribution_bins?: Array<{ bin_label: string; count: number; low: number; high: number }>
    /** 离散列 Top N 分布 */
    value_counts?: Array<{ value: string; count: number }>
    select_options?: string[]
  }>
  /** V2: 整体数据质量 summary */
  data_quality_summary?: {
    total_rows: number
    total_columns: number
    duplicate_rows: number
    empty_columns: string[]
    high_null_columns: string[]
  }
  /** V2: 建议的清洗操作 */
  cleaning_suggestions?: Array<{
    id: string; column: string | null; action: string
    strategy?: string | null; on_fail?: string | null
    affected_count: number; reason: string
    preview_before?: unknown[]; preview_after?: unknown[]
  }>
  /** V2: execute 后实际执行的清洗 */
  cleaning_applied?: Array<{
    action: string; column: string | null; strategy?: string | null; affected_rows: number
  }>
}

export interface ImportTaskInfo {
  task_id: ID; status: ImportTaskStatus; progress: number
  filename: string; format: string
  total_rows?: number | null; imported_rows?: number | null
  error_message?: string | null
  result_ids?: Array<number | string>
  created_at?: string | null; updated_at?: string | null
  /** analyze 阶段产出的校验报告（JSON） */
  validation_report?: ValidationReport | null
}

/** 表权限 */
export interface TablePermission {
  read_role?: string
  edit_records_role?: string
  edit_views_role?: string
  edit_schema_role?: string
  /** 数据治理（合并/清洗）最低角色阈值；空串表示使用默认 ADMIN */
  manage_data_role?: string
  /** 按角色分桶的隐藏字段: { "editor": ["field_name", ...], "viewer": [...] } */
  hidden_fields?: Record<string, string[]> | null
  row_filters?: Record<string, unknown> | null
}

// ── 数据治理（重复检测 / 合并 / 清洗） ──────────────

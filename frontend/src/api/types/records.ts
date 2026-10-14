/** 行记录、视图、审计日志、引用与回收站、CSV 结果. */

import type { ID } from './common'

export type RowValues = Record<string, unknown>

/** 后端返回的行数据 — 扁平 dict，业务字段直接以字段名作为 key，不再嵌套 values.
 * 例如：{ id: 1, '姓名': '张三', '薪资': 15000, created_at: '...' }
 */
export interface RowResponse {
  id: ID
  created_at?: string
  updated_at?: string
  created_by?: ID | null
  updated_by?: ID | null
  /** 业务字段以字段名直接作为 key，类型由各字段定义决定 */
  [fieldName: string]: unknown
}

export type RowDetail = RowResponse

/** 创建行的请求体：values 字段承载业务值 */
export interface RowCreate { values: RowValues }

/** 更新行的请求体：values 字段承载待更新的业务值子集 */
export interface RowUpdate { values: RowValues }
export interface RowListResponse { items: RowResponse[]; total: number; offset: number; limit: number }
export interface RecordListParams {
  offset?: number; limit?: number
  filters?: string | Record<string, unknown> | Array<Record<string, unknown>>
  sorts?: string | Record<string, unknown> | Array<Record<string, unknown>>
  filter_logic?: 'AND' | 'OR'
}

export interface View {
  id: ID; name: string; view_type: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  /** 视图级排序规则（后端字段名 sortings） */
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  /** 多条件组合方式（后端字段名 filter_type） */
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否默认视图（对齐后端 ViewResponse.is_default） */
  is_default: boolean; created_at?: string
  /** 视图归属：null=公共视图（有编辑视图权限者创建）；非空=个人视图（仅创建者可见可改） */
  owner_id?: number | null
  /** 排序权重（后端 DataView.order） */
  order?: number
}
export type ViewDetail = View
export interface ViewCreate {
  name: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否设为默认视图（对齐后端 ViewCreate.is_default） */
  is_default?: boolean
}
export interface ViewUpdate {
  name?: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR' | null
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否设为默认视图（对齐后端 ViewUpdate.is_default） */
  is_default?: boolean
}

export interface AuditLog {
  id: ID; table_id?: ID; row_id?: ID; action: string
  actor_id?: ID | null; actor_name?: string
  payload?: Record<string, unknown> | null; created_at?: string
}
export interface Reference {
  id: ID
  from_table_id: ID; from_row_id: ID; from_field_id: ID
  to_table_id: ID; to_row_id: ID; to_field_id: ID; created_at?: string
  /** 前端便捷展示用：被引用表 ID（同 to_table_id） */
  table_id?: ID
  /** 前端便捷展示用：被引用行 ID（同 to_row_id） */
  row_id?: ID
  /** 前端便捷展示用：被引用表名称 */
  table_name?: string
  /** 前端便捷展示用：被引用行摘要 */
  row_summary?: string
}

/** 回收站中的行 — 同样扁平结构 */
export interface TrashedRow {
  id: ID
  original_id?: ID
  deleted_at?: string
  /** 软删时间（后端可能返回 _trashed_at 或 deleted_at） */
  _trashed_at?: string
  [fieldName: string]: unknown
}

export interface CsvAnalyzeResult { columns: string[]; total_rows: number }
export interface CsvImportResult { table_id: ID; imported_rows: number; table_name?: string; imported?: number }

/** 通用文件导入分析结果（新） */

/** 数据治理任务、检测、合并与清洗. */

export type GovernanceTaskKind = 'detect' | 'merge' | 'clean'
export type GovernanceTaskStatus = 'pending' | 'running' | 'done' | 'failed'

/** 治理任务状态（对齐后端 GovernanceTaskOut） */
export interface GovernanceTask {
  id: number
  table_id: number
  user_id?: number | null
  kind: GovernanceTaskKind
  status: GovernanceTaskStatus
  progress: number
  config: Record<string, unknown>
  /** 原始 JSON 字符串；请用 governanceApi.report 解析后的接口 */
  report: string
  error_message: string
  total_groups: number
  done_groups: number
  created_at: string
  updated_at: string
}

export interface GovernanceDetectRequest {
  match_fields: string[]
  ignore_case?: boolean
  ignore_whitespace?: boolean
}

export type Survivorship = 'non_empty_first' | 'latest' | 'oldest' | 'manual'

export interface GovernanceMergeGroup {
  member_row_ids: number[]
  survivor_row_id: number
  survivorship?: Survivorship
  field_policies?: Record<string, Survivorship>
  manual_values?: Record<string, unknown>
}

export interface GovernanceMergeRequest {
  match_fields?: string[]
  ignore_case?: boolean
  ignore_whitespace?: boolean
  groups: GovernanceMergeGroup[]
}

export interface GovernanceCleanAction {
  action: 'trim_whitespace' | 'fill_null' | 'coerce_type' | 'drop_outliers'
  column: string
  strategy?: string | null
  on_fail?: 'nullify' | 'reject'
  fill_value?: unknown
}

export interface GovernanceCleanRequest {
  actions: GovernanceCleanAction[]
  preview: boolean
}

// ── Attachment ──────────────────────────────────────

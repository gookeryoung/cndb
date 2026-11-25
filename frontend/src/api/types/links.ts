/** 工作区链接（ADR 0154）：跨工作区只读引用 */

import type { ID } from './common'

export type WorkspaceLinkStatus = 'pending' | 'active' | 'rejected' | 'expired'

/** 链接（对齐后端 WorkspaceLinkResponse） */
export interface WorkspaceLink {
  id: ID
  workspace_id: ID
  source_workspace_id: ID
  source_workspace_name: string
  target_type: 'table' | 'view'
  target_table_id: ID
  target_table_name: string
  target_view_id: ID | null
  alias: string
  status: WorkspaceLinkStatus
  ttl_days: number
  expires_at: string | null
  created_by_id: ID | null
  approved_by_name: string | null
  approved_at: string | null
  note: string
  /** 当前用户此刻能否读到数据（源工作区 READ 且链接生效） */
  readable: boolean
  created_at: string
  updated_at: string
}

export interface WorkspaceLinkCreate {
  source_workspace_id: ID
  target_table_id: ID
  target_view_id?: ID | null
  alias?: string | null
  ttl_days?: number
  note?: string
}

/** 链接可读字段（对齐后端 field_response 的必要字段） */
export interface LinkField {
  id: ID
  name: string
  field_type: string
  order?: number
  config?: Record<string, unknown> | null
}

export interface LinkRowsResponse {
  rows: Array<Record<string, unknown>>
  total: number
  limit: number
  offset: number
  link_id: ID
  target_type: 'table' | 'view'
}

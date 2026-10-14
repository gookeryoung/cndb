/** 修改申请（双轨制写入载体）. */

import type { ID } from './common'
import type { RowResponse } from './records'

export type ChangeOp = 'create' | 'update' | 'delete'

export type CRStatus = 'open' | 'merged' | 'closed'

/** 修改申请（对齐后端 serialize_request） */
export interface ChangeRequest {
  id: ID
  workspace_id: ID
  table_id: ID
  title: string
  description: string
  status: CRStatus
  /** 基准过期标记：其他申请合并了相同行后置 true，需 update-base 刷新 */
  stale: boolean
  submitted_by_id: ID | null
  reviewed_by_id: ID | null
  reviewed_at?: string | null
  review_comment?: string | null
  created_at?: string
  updated_at?: string
  /** 与其他 open 申请共享的行数（去重，仅列表响应附带） */
  conflicts_count?: number
}

/** 申请内单条变更项（详情响应含字段级 diff 与冲突标记） */
export interface ChangeItemDetail {
  id: ID
  op: ChangeOp
  row_id: ID | null
  /** 提交时目标行涉及字段的原值快照（冲突检测基准） */
  base_values: Record<string, unknown>
  /** 新值增量 */
  values: Record<string, unknown>
  /** 当前行实时值（delete 项为整行快照） */
  current_values: Record<string, unknown>
  /** 发生基准漂移的字段名清单 */
  field_conflicts: string[]
}

/** 申请动作流水（评论与处理动作统一记录） */
export interface ChangeActionItem {
  id: ID
  action: 'comment' | 'merge' | 'close' | 'reopen' | 'update_base'
  comment: string | null
  acted_by_id: ID | null
  created_at?: string
}

export interface ChangeRequestDetail extends ChangeRequest {
  items: ChangeItemDetail[]
  actions: ChangeActionItem[]
}

export interface ChangeRequestPage { items: ChangeRequest[]; total: number; write_mode?: TableWriteMode }

/** 当前用户对表的写模式（与后端双轨写分派同源）：
 *  direct=原地修改直存；change_request=写路径自动生成修改申请；denied=表级编辑受限（403） */
export type TableWriteMode = 'direct' | 'change_request' | 'denied'

export interface CRCreatePayload {
  title?: string
  description?: string
  items: Array<{ op: ChangeOp; row_id?: ID; values?: Record<string, unknown> }>
}

export interface CRMergePayload {
  items: Array<{ item_id: ID; action: 'apply' | 'skip' }>
  comment?: string
}

/** 写路径双轨分派的 202 响应：未落库，转为修改申请（单 item） */
export interface ChangeRequestDispatchResponse {
  change_request: ChangeRequest
}

/** 经表单/批量删除提交的多 item 申请响应（后端 202 载荷） */
export interface ChangeRequestBatchResponse extends ChangeRequestDispatchResponse {
  created_items?: unknown[]
}

/** 判定写响应是否为 202 修改申请载荷（而非直存 RowResponse） */
export function isChangeRequestResponse(r: RowResponse | ChangeRequestBatchResponse | unknown): r is ChangeRequestBatchResponse {
  return typeof r === 'object' && r !== null && 'change_request' in r
}

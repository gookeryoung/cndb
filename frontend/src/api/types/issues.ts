/** 问题反馈与评论/事件流水. */

import type { ID } from './common'

export type IssueStatus = 'open' | 'closed'

export type IssueCategory = 'data_error' | 'suggestion' | 'question' | 'other'

/** 问题详情/创建响应（对齐后端 get_issue_detail） */
export interface Issue {
  id: ID
  workspace_id: ID
  table_id: ID
  title: string
  description: string
  category: IssueCategory
  status: IssueStatus
  created_by_id: ID | null
  created_at?: string
  updated_at?: string
}

/** 问题列表项（附评论数） */
export interface IssueListItem extends Issue {
  comment_count: number
}

export interface IssuePage { items: IssueListItem[]; total: number }

export interface IssueComment {
  id: ID
  issue_id: ID
  content: string
  created_by_id: ID | null
  created_at?: string
}

/** 问题状态流水事件（谁在何时关闭/重开） */
export interface IssueEvent {
  id: ID
  issue_id: ID
  action: 'created' | 'closed' | 'reopened'
  actor_id: ID | null
  created_at?: string
}

/** 问题详情（本体 + 评论 + 事件流） */
export interface IssueDetail extends Issue {
  comments: IssueComment[]
  events: IssueEvent[]
}

export interface IssueCreatePayload {
  title: string
  description?: string
  category?: IssueCategory
}

// ── 修改申请（change_requests 插件） ────────────────

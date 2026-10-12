/** 问题清单 API — /api/v1/workspaces/{wid}/tables/{tid}/issues */

import api from './client'
import type { IssueCreatePayload, IssueDetail, IssuePage } from './types'

export const issuesApi = {
  /** 问题列表，默认 open（GitHub 式两栏过滤） */
  list: (wid: number | string, tid: number | string, status: 'open' | 'closed' | 'all' = 'open') =>
    api.get<IssuePage>(`/v1/workspaces/${wid}/tables/${tid}/issues`, { params: { status } }).then(r => r.data),
  /** 详情 = 本体 + comments + events */
  get: (wid: number | string, tid: number | string, issueId: number | string) =>
    api.get<IssueDetail>(`/v1/workspaces/${wid}/tables/${tid}/issues/${issueId}`).then(r => r.data),
  /** 提交问题（所有成员），返回详情 */
  create: (wid: number | string, tid: number | string, data: IssueCreatePayload) =>
    api.post<IssueDetail>(`/v1/workspaces/${wid}/tables/${tid}/issues`, data).then(r => r.data),
  /** 评论（所有成员），返回评论实体 */
  addComment: (wid: number | string, tid: number | string, issueId: number | string, content: string) =>
    api.post<{ id: number; issue_id: number; content: string; created_by_id: number | null; created_at?: string }>(
      `/v1/workspaces/${wid}/tables/${tid}/issues/${issueId}/comments`, { content },
    ).then(r => r.data),
  /** 关闭（owner/editor 或创建者），返回详情 */
  close: (wid: number | string, tid: number | string, issueId: number | string) =>
    api.post<IssueDetail>(`/v1/workspaces/${wid}/tables/${tid}/issues/${issueId}/close`).then(r => r.data),
  /** 重开（owner/editor 或创建者），返回详情 */
  reopen: (wid: number | string, tid: number | string, issueId: number | string) =>
    api.post<IssueDetail>(`/v1/workspaces/${wid}/tables/${tid}/issues/${issueId}/reopen`).then(r => r.data),
}

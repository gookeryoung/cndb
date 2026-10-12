/** 修改申请 API — /api/v1/workspaces/{wid}/tables/{tid}/change-requests */

import api from './client'
import type { ChangeRequestDetail, ChangeRequestPage, CRMergePayload, CRCreatePayload } from './types'

export const changeRequestsApi = {
  /** 列表：scope=open/all/mine，列表项附 conflicts_count */
  list: (wid: number | string, tid: number | string, scope: 'open' | 'all' | 'mine' = 'open') =>
    api.get<ChangeRequestPage>(`/v1/workspaces/${wid}/tables/${tid}/change-requests`, { params: { scope } }).then(r => r.data),
  /** 详情 = 本体 + items（字段级 diff）+ actions 流水 */
  get: (wid: number | string, tid: number | string, requestId: number | string) =>
    api.get<ChangeRequestDetail>(`/v1/workspaces/${wid}/tables/${tid}/change-requests/${requestId}`).then(r => r.data),
  /** 创建（支持多 item），返回详情 */
  create: (wid: number | string, tid: number | string, data: CRCreatePayload) =>
    api.post<ChangeRequestDetail>(`/v1/workspaces/${wid}/tables/${tid}/change-requests`, data).then(r => r.data),
  /** 逐项决策合并（仅 owner/editor），返回 { applied, skipped, request } */
  merge: (wid: number | string, tid: number | string, requestId: number | string, data: CRMergePayload) =>
    api.post<{ applied: number; skipped: number; request: ChangeRequestDetail }>(
      `/v1/workspaces/${wid}/tables/${tid}/change-requests/${requestId}/merge`, data,
    ).then(r => r.data),
  /** 关闭（owner/editor 或提交人），返回申请本体 */
  close: (wid: number | string, tid: number | string, requestId: number | string) =>
    api.post<ChangeRequestDetail>(`/v1/workspaces/${wid}/tables/${tid}/change-requests/${requestId}/close`).then(r => r.data),
  /** 重开（仅 owner/editor，仅 closed 可重开） */
  reopen: (wid: number | string, tid: number | string, requestId: number | string) =>
    api.post<ChangeRequestDetail>(`/v1/workspaces/${wid}/tables/${tid}/change-requests/${requestId}/reopen`).then(r => r.data),
  /** 基准刷新（仅提交人，stale 时重读当前行快照 base_values） */
  updateBase: (wid: number | string, tid: number | string, requestId: number | string) =>
    api.post<ChangeRequestDetail>(`/v1/workspaces/${wid}/tables/${tid}/change-requests/${requestId}/update-base`).then(r => r.data),
  /** 评论（所有成员），返回动作流水实体 */
  addComment: (wid: number | string, tid: number | string, requestId: number | string, content: string) =>
    api.post<{ id: number; action: string; comment: string | null; acted_by_id: number | null; created_at?: string }>(
      `/v1/workspaces/${wid}/tables/${tid}/change-requests/${requestId}/comments`, { content },
    ).then(r => r.data),
}

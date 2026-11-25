/** 工作区链接 API（ADR 0154）：申请 / 审批 / 撤回 + 只读 fields / rows / export */

import api from './client'
import type { LinkField, LinkRowsResponse, WorkspaceLink, WorkspaceLinkCreate } from './types'

export const linksApi = {
  list: (wid: number | string) =>
    api.get<WorkspaceLink[]>(`/v1/workspaces/${wid}/links`).then(r => r.data),
  /** 源工作区视角：待我批准的链接 */
  inbox: (wid: number | string) =>
    api.get<WorkspaceLink[]>(`/v1/workspaces/${wid}/links/inbox`).then(r => r.data),
  create: (wid: number | string, data: WorkspaceLinkCreate) =>
    api.post<WorkspaceLink>(`/v1/workspaces/${wid}/links`, data).then(r => r.data),
  approve: (wid: number | string, linkId: number | string, ttlDays?: number) =>
    api
      .post<WorkspaceLink>(`/v1/workspaces/${wid}/links/${linkId}/approve`, { ttl_days: ttlDays ?? null })
      .then(r => r.data),
  reject: (wid: number | string, linkId: number | string) =>
    api.post<WorkspaceLink>(`/v1/workspaces/${wid}/links/${linkId}/reject`).then(r => r.data),
  remove: (wid: number | string, linkId: number | string) =>
    api.delete(`/v1/workspaces/${wid}/links/${linkId}`).then(r => r.data),
  fields: (wid: number | string, linkId: number | string) =>
    api
      .get<{ link_id: number; table_id: number; table_name: string; target_type: string; fields: LinkField[] }>(
        `/v1/workspaces/${wid}/links/${linkId}/fields`,
      )
      .then(r => r.data),
  rows: (
    wid: number | string,
    linkId: number | string,
    params: { offset?: number; limit?: number; filters?: string; sorts?: string; filter_logic?: string } = {},
  ) =>
    api
      .get<LinkRowsResponse>(`/v1/workspaces/${wid}/links/${linkId}/rows`, { params })
      .then(r => r.data),
  /** CSV 导出（只读、受同一行列裁剪与上限） */
  exportCsv: (wid: number | string, linkId: number | string) =>
    api
      .get(`/v1/workspaces/${wid}/links/${linkId}/export`, { responseType: 'blob' })
      .then(r => r.data as Blob),
}

export default linksApi

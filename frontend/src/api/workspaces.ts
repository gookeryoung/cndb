/** 工作区 API — /api/v1/workspaces/*（含成员、pin、导入导出） */

import api from './client'
import type {
  WorkspaceCreate, WorkspaceUpdate, Workspace, WorkspaceDetail, WorkspaceMember,
  WorkspaceExportData,
} from './types'

export const workspaceApi = {
  list: () => api.get<Array<Workspace & { pinned?: boolean }>>('/v1/workspaces').then(r => r.data),
  create: (data: WorkspaceCreate) =>
    api.post<Workspace>('/v1/workspaces', data).then(r => r.data),
  get: (wid: number | string) =>
    api.get<WorkspaceDetail>(`/v1/workspaces/${wid}`).then(r => r.data),
  update: (wid: number | string, data: WorkspaceUpdate) =>
    api.patch<Workspace>(`/v1/workspaces/${wid}`, data).then(r => r.data),
  remove: (wid: number | string) =>
    api.delete(`/v1/workspaces/${wid}`).then(r => r.data),
  /** 切换 pin 状态（toggle） */
  togglePin: (wid: number | string) =>
    api.post<{ pinned: boolean }>('/v1/workspaces/pin', { workspace_id: wid }).then(r => r.data),
  members: (wid: number | string) =>
    api.get<WorkspaceMember[]>(`/v1/workspaces/${wid}/members`).then(r => r.data),
  /** 搜索可添加的候选用户 */
  memberCandidates: (wid: number | string, search = '') =>
    api.get<{ results: Array<{ id: number; username: string; nickname?: string; email?: string }> }>(
      `/v1/workspaces/${wid}/members/candidates`, { params: { search } },
    ).then(r => r.data),
  addMember: (wid: number | string, username: string, role: string) =>
    api.post<WorkspaceMember>(`/v1/workspaces/${wid}/members`, { username, role }).then(r => r.data),
  updateMemberRole: (wid: number | string, memberId: number | string, role: string) =>
    api.patch<WorkspaceMember>(`/v1/workspaces/${wid}/members/${memberId}`, { role }).then(r => r.data),
  removeMember: (wid: number | string, memberId: number | string) =>
    api.delete(`/v1/workspaces/${wid}/members/${memberId}`).then(() => true),
  /** 转让工作区所有权（仅 owner 可执行） */
  transferOwner: (wid: number | string, userId: number) =>
    api.post<WorkspaceMember>(`/v1/workspaces/${wid}/owner`, { user_id: userId }).then(r => r.data),
  /** 导出整个工作区为 JSON（结构+数据+视图） */
  exportWorkspace: (wid: number | string) =>
    api.get<WorkspaceExportData>(`/v1/workspaces/${wid}/export`).then(r => r.data),
  /** 从 JSON 数据导入工作区（创建新表、字段、数据、视图） */
  importWorkspace: (wid: number | string, jsonData: Record<string, unknown>) =>
    api.post<{ imported_tables: number; imported_rows: number; imported_views: number }>(
      `/v1/workspaces/${wid}/import`,
      { json_data: jsonData },
    ).then(r => r.data),
  /** 从备份 JSON 创建全新工作区（同时导入表结构、数据和视图） */
  importFromBackup: (payload: { name?: string; json_data: Record<string, unknown> }) =>
    api.post<{ workspace: Workspace; imported_tables: number; imported_rows: number; imported_views: number }>(
      '/v1/workspaces/import',
      payload,
    ).then(r => r.data),
}

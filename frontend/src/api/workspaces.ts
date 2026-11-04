/** 工作区 API — /api/v1/workspaces/*（含成员、pin、导入导出） */

import api from './client'
import type {
  WorkspaceCreate, WorkspaceUpdate, Workspace, WorkspaceDetail, WorkspaceMember,
  WorkspaceArchiveInspect,
} from './types'

export const workspaceApi = {
  list: () =>
    api
      .get<
        Array<
          Workspace & {
            pinned?: boolean
            table_count?: number
            member_count?: number
            document_count?: number
            design_count?: number
          }
        >
      >('/v1/workspaces')
      .then(r => r.data),
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
  /** 导出工作区全量备份归档（tar.gz，含版本历史/草稿/议题/附件等，可含密钥） */
  exportWorkspaceArchive: (wid: number | string, includeSecrets: boolean) =>
    api.get(`/v1/workspaces/${wid}/export/archive`, {
      params: { include_secrets: includeSecrets },
      responseType: 'blob',
    }).then(r => r.data as Blob),
  /** 从 v9 归档覆盖恢复当前工作区（危险操作：清空现有业务数据后重建） */
  restoreWorkspace: (wid: number | string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    // multipart 必须显式声明，拦截器会删掉让浏览器补 boundary；
    // 实例默认头是 application/json，漏了它 axios 会把 FormData 序列化成 JSON → 后端 422
    return api.post<{
      imported_tables: number; imported_rows: number; imported_views: number
      imported_documents?: number; errors?: string[]
    }>(`/v1/workspaces/${wid}/restore`, form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(r => r.data)
  },
  /** 归档导入预检：读取归档内工作区名 / 版本 / 统计，并判断同名 owner 工作区是否存在 */
  inspectWorkspaceArchive: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<WorkspaceArchiveInspect>(
      '/v1/workspaces/import/archive/inspect', form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    ).then(r => r.data)
  },
  /** 从 v9 归档创建全新工作区（owner 为当前用户）；name 非空时覆盖归档内名称 */
  importWorkspaceArchive: (file: File, name?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (name?.trim()) form.append('name', name.trim())
    // 同上：multipart 必须显式声明，否则被 axios 按 JSON 序列化
    return api.post<{ workspace: Workspace } & {
      imported_tables: number; imported_rows: number; imported_views: number
      imported_documents?: number; errors?: string[]
    }>('/v1/workspaces/import/archive', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(r => r.data)
  },
}

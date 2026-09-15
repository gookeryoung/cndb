/** 工作区接口. */
import { request } from './client'

export interface WorkspaceSummary {
  id: number
  name: string
  description: string | null
  visibility: string
  pinned: boolean
  tags: string[]
  allow_edit: boolean
  table_count?: number
  member_count?: number
  current_user_role?: string | null
}

export const workspaceApi = {
  list: () => request<WorkspaceSummary[]>({ url: '/v1/workspaces' }),

  get: (wid: number | string) =>
    request<Record<string, unknown>>({ url: `/v1/workspaces/${wid}` }),

  togglePin: (wid: number | string) =>
    request<{ pinned: boolean }>({
      url: '/v1/workspaces/pin',
      method: 'POST',
      data: { workspace_id: wid },
    }),
}

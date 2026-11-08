/** 工作区项目上下文 API（ADR 0122）— /api/v1/workspaces/{wid}/projects */

import api from './client'

export interface ProjectListItem {
  project_row_id: number
  title: string
  stage_key: string | null
  stage_name: string | null
  gate_satisfied: boolean
  missing_forms: string[]
  missing_documents: string[]
  initialized: boolean
  updated_at?: string | null
}

export interface ProjectListResponse {
  project_mode: 'workspace' | 'project'
  root_form: string | null
  link_field: string | Record<string, string> | null
  title_field: string | null
  items: ProjectListItem[]
  total: number
}

export interface ProjectModeEnableResult {
  project_mode: string
  projects: number
  initialized: number
  documents_created: number
}

const base = (wid: number | string) => `/v1/workspaces/${wid}/projects`

export const workspaceProjectsApi = {
  list: (wid: number | string, params?: { limit?: number; offset?: number }) =>
    api.get<ProjectListResponse>(base(wid), { params }).then(r => r.data),

  enableProjectMode: (wid: number | string, generateDocuments = false) =>
    api
      .post<ProjectModeEnableResult>(`/v1/workspaces/${wid}/project-mode/enable`, {
        generate_documents: generateDocuments,
      })
      .then(r => r.data),

  /** 按规则补建单个项目的缺失文档（不覆盖正文） */
  ensureDocuments: (wid: number | string, projectRowId: number) =>
    api
      .post<{ project_row_id: number; created: number }>(`${base(wid)}/${projectRowId}/documents`)
      .then(r => r.data),
}

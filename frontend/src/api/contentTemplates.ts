/** 文档内容模板 API — `/api/v1/workspaces/{wid}/document-content-templates`（需求 0169）.
 *
 * 与导出排版模板（`exportTemplates.ts`，ADR 0152）完全独立：本接口只管
 * 「从模板新建文档」用的 Markdown 正文骨架。
 */

import api from './client'

export interface ContentTemplateItem {
  id: number
  workspace_id: number
  name: string
  content_markdown: string
  description: string
  icon: string
  sort_order: number
  created_by_id: number | null
  created_at: string | null
  updated_at: string | null
}

export interface ContentTemplateList {
  items: ContentTemplateItem[]
  total: number
}

export interface ContentTemplateCreatePayload {
  name: string
  content_markdown?: string
  description?: string
  icon?: string
  sort_order?: number
}

export type ContentTemplateUpdatePayload = Partial<ContentTemplateCreatePayload>

const base = (wid: number | string) => `/v1/workspaces/${wid}/document-content-templates`

export const contentTemplateApi = {
  list: (wid: number | string) => api.get<ContentTemplateList>(base(wid)).then(r => r.data),
  get: (wid: number | string, id: number) =>
    api.get<ContentTemplateItem>(`${base(wid)}/${id}`).then(r => r.data),
  create: (wid: number | string, payload: ContentTemplateCreatePayload) =>
    api.post<ContentTemplateItem>(base(wid), payload).then(r => r.data),
  update: (wid: number | string, id: number, payload: ContentTemplateUpdatePayload) =>
    api.patch<ContentTemplateItem>(`${base(wid)}/${id}`, payload).then(r => r.data),
  remove: (wid: number | string, id: number) =>
    api.delete<{ ok: boolean }>(`${base(wid)}/${id}`).then(r => r.data),
}

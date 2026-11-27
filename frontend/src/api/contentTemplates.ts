/** 文档内容模板 API — `/api/v1/workspaces/{wid}/document-content-templates`（需求 0169 / ADR 0177）.
 *
 * 模型与导出模板（`exportTemplates.ts`，ADR 0152）独立，只共用后端的
 * `services/templates_common`（名称唯一 / 404 / `{items, total}` 载荷）；
 * 本接口只管「从模板新建文档」用的 Markdown 正文骨架。
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
  /** 内容模板自带的排版模板（ADR 0177 C6）：`builtin:<key>` 或导出模板 id；null = 不绑定 */
  export_template_ref: string | null
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
  export_template_ref?: string | null
}

export type ContentTemplateUpdatePayload = Partial<ContentTemplateCreatePayload>

/** 内置库（ADR 0185 D4）：后端代码常量，只读、不入库、不进备份 */
export interface BuiltinContentTemplate {
  /** `builtin:<key>`，与导出模板 ref 同形但 key 集合不重叠（I3） */
  ref: string
  key: string
  name: string
  description: string
  icon: string
  sort_order: number
  /** 内置模板声明的排版模板绑定（可空 = 跟随工作区默认） */
  export_template_ref: string | null
  content_markdown: string
}

export interface BuiltinContentCategory {
  key: string
  name: string
  description: string
  sort_order: number
  templates: BuiltinContentTemplate[]
}

export interface BuiltinContentLibrary {
  categories: BuiltinContentCategory[]
}

const base = (wid: number | string) => `/v1/workspaces/${wid}/document-content-templates`

export const contentTemplateApi = {
  list: (wid: number | string) => api.get<ContentTemplateList>(base(wid)).then(r => r.data),
  /** 内置库（ADR 0185 D4）：只读、一次返回全部正文，自定义列表端点载荷不变 */
  listBuiltin: (wid: number | string) =>
    api.get<BuiltinContentLibrary>(`${base(wid)}/builtin`).then(r => r.data),
  get: (wid: number | string, id: number) =>
    api.get<ContentTemplateItem>(`${base(wid)}/${id}`).then(r => r.data),
  create: (wid: number | string, payload: ContentTemplateCreatePayload) =>
    api.post<ContentTemplateItem>(base(wid), payload).then(r => r.data),
  /** 更新：PUT 与 PATCH 等价（ADR 0177 D6），这里统一走 PATCH */
  update: (wid: number | string, id: number, payload: ContentTemplateUpdatePayload) =>
    api.patch<ContentTemplateItem>(`${base(wid)}/${id}`, payload).then(r => r.data),
  remove: (wid: number | string, id: number) =>
    api.delete<{ ok: boolean }>(`${base(wid)}/${id}`).then(r => r.data),
  /** 创建副本（ADR 0177 C5）：名称「原名 副本」并递增 */
  duplicate: (wid: number | string, id: number) =>
    api.post<ContentTemplateItem>(`${base(wid)}/${id}/duplicate`).then(r => r.data),
}

/** 表单 API — /api/v1/workspaces/{wid}/forms/*（表单定义 CRUD + 表单行增删查改） */

import api from './client'
import type {
  FormCreate,
  FormDefinition,
  FormListItem,
  FormMeta,
  FormRowCreateResponse,
  FormRowListResponse,
  FormUpdate,
  RowResponse,
} from './types'

export const formApi = {
    /** 表单定义列表（仅含当前用户可读表上的表单） */
    list: (wid: number | string) =>
        api.get<FormListItem[]>(`/v1/workspaces/${wid}/forms`).then(r => r.data),
    get: (wid: number | string, formId: number | string) =>
        api.get<FormDefinition>(`/v1/workspaces/${wid}/forms/${formId}`).then(r => r.data),
    create: (wid: number | string, data: FormCreate) =>
        api.post<FormDefinition>(`/v1/workspaces/${wid}/forms`, data).then(r => r.data),
    update: (wid: number | string, formId: number | string, data: FormUpdate) =>
        api.patch<FormDefinition>(`/v1/workspaces/${wid}/forms/${formId}`, data).then(r => r.data),
    remove: (wid: number | string, formId: number | string) =>
        api.delete(`/v1/workspaces/${wid}/forms/${formId}`).then(r => r.data),
    /** 表单运行时元数据（字段配置 + 失效清单 + 当前用户操作位） */
    meta: (wid: number | string, formId: number | string) =>
        api.get<FormMeta>(`/v1/workspaces/${wid}/forms/${formId}/meta`).then(r => r.data),
    /** 新建行：绑定审批流时返回 { approval }，否则返回行数据 */
    createRow: (wid: number | string, formId: number | string, values: Record<string, unknown>) =>
        api.post<FormRowCreateResponse>(`/v1/workspaces/${wid}/forms/${formId}/rows`, { values }).then(r => r.data),
    listRows: (wid: number | string, formId: number | string, limit = 50, offset = 0) =>
        api.get<FormRowListResponse>(`/v1/workspaces/${wid}/forms/${formId}/rows`, { params: { limit, offset } }).then(r => r.data),
    updateRow: (wid: number | string, formId: number | string, rowId: number | string, values: Record<string, unknown>) =>
        api.patch<RowResponse>(`/v1/workspaces/${wid}/forms/${formId}/rows/${rowId}`, { values }).then(r => r.data),
    deleteRow: (wid: number | string, formId: number | string, rowId: number | string) =>
        api.delete(`/v1/workspaces/${wid}/forms/${formId}/rows/${rowId}`).then(r => r.data),
}

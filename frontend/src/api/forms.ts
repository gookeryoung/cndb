/** 表单定义 API — forms 插件，挂载 /api/v1/workspaces/{wid}/forms */

import api from './client'
import type {
  FormDefinition, FormDefinitionSummary, FormDefinitionCreate, FormDefinitionUpdate,
  FormSubmitRequest, FormSubmitResponse,
} from './types'

export const formApi = {
  /** 列出工作区内表单定义 */
  list: (workspaceId: number | string) =>
    api.get<FormDefinitionSummary[]>(`/v1/workspaces/${workspaceId}/forms`).then(r => r.data),
  /** 获取表单详情 */
  get: (workspaceId: number | string, formId: number | string) =>
    api.get<FormDefinition>(`/v1/workspaces/${workspaceId}/forms/${formId}`).then(r => r.data),
  /** 创建表单定义 */
  create: (workspaceId: number | string, data: FormDefinitionCreate) =>
    api.post<FormDefinition>(`/v1/workspaces/${workspaceId}/forms`, data).then(r => r.data),
  /** 更新表单定义 */
  update: (workspaceId: number | string, formId: number | string, data: FormDefinitionUpdate) =>
    api.put<FormDefinition>(`/v1/workspaces/${workspaceId}/forms/${formId}`, data).then(r => r.data),
  /** 删除表单定义（软删除） */
  remove: (workspaceId: number | string, formId: number | string) =>
    api.delete(`/v1/workspaces/${workspaceId}/forms/${formId}`).then(r => r.data),
  /** 表单运行器提交：创建表记录 */
  submit: (workspaceId: number | string, formId: number | string, data: FormSubmitRequest) =>
    api.post<FormSubmitResponse>(`/v1/workspaces/${workspaceId}/forms/${formId}/submit`, data).then(r => r.data),
}

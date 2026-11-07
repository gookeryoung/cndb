/** 工作区模板 / 生命周期 API — /api/v1/workspace-templates 与 /workspaces/:id/lifecycle */

import api from './client'
import { parseContentDispositionFilename } from '@/utils/disposition'
import type {
  LifecycleStage, TemplateImportPayload, TemplateImportPreview, TemplatePreview, TemplateRevision,
  TemplateSpec, TemplateUpdateResult, WorkspaceLifecycle, WorkspaceTemplate,
} from './types'

export const workspaceTemplateApi = {
  list: (q?: string) =>
    api.get<WorkspaceTemplate[]>('/v1/workspace-templates', { params: q ? { q } : undefined })
      .then(r => r.data),
  get: (id: number | string) =>
    api.get<WorkspaceTemplate>(`/v1/workspace-templates/${id}`).then(r => r.data),
  create: (data: {
    name: string; description?: string; category?: string;
    modules?: string[]; spec: TemplateSpec; change_summary?: string
  }) => api.post<WorkspaceTemplate>('/v1/workspace-templates', data).then(r => r.data),
  preview: (id: number | string, spec: TemplateSpec) =>
    api.post<TemplatePreview>(`/v1/workspace-templates/${id}/preview`, { spec }).then(r => r.data),
  update: (id: number | string, data: {
    name?: string; description?: string; category?: string;
    modules?: string[]; spec?: TemplateSpec; change_summary?: string; force?: boolean
  }) => api.put<TemplateUpdateResult>(`/v1/workspace-templates/${id}`, data).then(r => r.data),
  revisions: (id: number | string) =>
    api.get<TemplateRevision[]>(`/v1/workspace-templates/${id}/revisions`).then(r => r.data),
  remove: (id: number | string) =>
    api.delete(`/v1/workspace-templates/${id}`).then(() => true),
  /** 导出单个模板为 .workspace-template.json（文件名取后端 Content-Disposition） */
  exportFile: (id: number | string) =>
    api.get<Blob>(`/v1/workspace-templates/${id}/export`, { responseType: 'blob' })
      .then(r => ({
        blob: r.data,
        filename: parseContentDispositionFilename(r.headers?.['content-disposition'])
          ?? 'workspace-template.json',
      })),
  /** 导入预览：只校验不落库，返回归一化规格与建议名称 */
  importPreview: (payload: TemplateImportPayload) =>
    api.post<TemplateImportPreview>('/v1/workspace-templates/import/preview', payload).then(r => r.data),
  /** 导入创建：同名自动重命名，返回新模板 */
  importFile: (payload: TemplateImportPayload) =>
    api.post<WorkspaceTemplate>('/v1/workspace-templates/import', payload).then(r => r.data),
}

export const workspaceLifecycleApi = {
  get: (wid: number | string) =>
    api.get<WorkspaceLifecycle>(`/v1/workspaces/${wid}/lifecycle`).then(r => r.data),
  advance: (wid: number | string, data: { target_stage?: string; force?: boolean; reason?: string }) =>
    api.post<WorkspaceLifecycle>(`/v1/workspaces/${wid}/lifecycle/advance`, data).then(r => r.data),
  apply: (wid: number | string, data: { template_id: number; force?: boolean }) =>
    api.post<{ workspace_id: number; template_id: number; template_version: number; template_stage: string | null; sync: Record<string, number> }>(
      `/v1/workspaces/${wid}/lifecycle/apply`, data,
    ).then(r => r.data),
}

export type { LifecycleStage }

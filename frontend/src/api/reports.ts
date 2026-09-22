/** 报告模板 API — reports 插件挂载 /api/v1/reports */

import api from './client'
import type {
  ReportTemplate, ReportTemplateSummary, ReportTemplateCreate, ReportTemplateUpdate,
  ReportRenderRequest,
} from './types'

export const reportApi = {
  /** 列出所有报告模板 */
  list: () => api.get<ReportTemplateSummary[]>('/v1/reports').then(r => r.data),
  /** 获取模板详情（含 template_content） */
  get: (id: number | string) => api.get<ReportTemplate>(`/v1/reports/${id}`).then(r => r.data),
  /** 创建报告模板 */
  create: (data: ReportTemplateCreate) => api.post<ReportTemplate>('/v1/reports', data).then(r => r.data),
  /** 更新报告模板 */
  update: (id: number | string, data: ReportTemplateUpdate) => api.put<ReportTemplate>(`/v1/reports/${id}`, data).then(r => r.data),
  /** 删除报告模板 */
  remove: (id: number | string) => api.delete(`/v1/reports/${id}`).then(r => r.data),
  /** 渲染报告（返回文件二进制） */
  render: (id: number | string, data: ReportRenderRequest) =>
    api.post<Blob>(`/v1/reports/${id}/render`, data, { responseType: 'blob' }).then(r => r.data),
}

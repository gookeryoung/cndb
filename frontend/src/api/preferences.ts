/** 用户偏好 API — /api/v1/accounts/preferences/*（ADR 0021：主页收藏视图与自定义顺序） */

import api from './client'
import type {
  DashboardTemplate,
  DashboardTemplateSavePayload,
  FavoriteViewSummary,
  UserPreferences,
} from './types'

export const preferencesApi = {
  /** 当前用户完整偏好（激活视图 + 工作区顺序 + 收藏视图 id） */
  get: () =>
    api.get<UserPreferences>('/v1/accounts/preferences').then(r => r.data),
  /** 「我的视图」摘要（按收藏顺序；后端读取时剪枝失效引用） */
  listFavoriteViews: () =>
    api.get<FavoriteViewSummary[]>('/v1/accounts/preferences/favorite-views').then(r => r.data),
  /** 全量替换收藏视图（顺序即展示顺序）；不可见 / 不可读 id 由后端静默丢弃 */
  setFavoriteViews: (viewIds: Array<number | string>) =>
    api
      .put<{ view_ids: number[] }>('/v1/accounts/preferences/favorite-views', {
        view_ids: viewIds.map(Number),
      })
      .then(r => r.data),
  /** 全量替换主页工作区顺序；非成员工作区由后端静默丢弃 */
  setWorkspaceOrder: (workspaceIds: Array<number | string>) =>
    api
      .put<{ workspace_ids: number[] }>('/v1/accounts/preferences/workspace-order', {
        workspace_ids: workspaceIds.map(Number),
      })
      .then(r => r.data),
  /** dashboard 模板列表（新保存的在前；ADR 0023 P3） */
  listDashboardTemplates: () =>
    api.get<DashboardTemplate[]>('/v1/accounts/preferences/dashboard-templates').then(r => r.data),
  /** 另存为模板；同名模板原地覆盖（保留 id） */
  saveDashboardTemplate: (payload: DashboardTemplateSavePayload) =>
    api
      .post<DashboardTemplate>('/v1/accounts/preferences/dashboard-templates', payload)
      .then(r => r.data),
  /** 删除模板；后端不存在返回 404 */
  deleteDashboardTemplate: (templateId: string) =>
    api.delete(`/v1/accounts/preferences/dashboard-templates/${encodeURIComponent(templateId)}`),
}

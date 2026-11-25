/** 主页聚合 API — `/api/v1/home/*`（ADR 0160 P2）.
 *
 * 只读：跨工作区待办计数。载荷只有聚合数（不含工作区 id / 名称 / 条目标题），
 * `partial=true` 表示至少一个工作区统计失败并已降级为 0（HTTP 仍 200）。
 */

import api from './client'

/** 待办计数（三项之和 = total） */
export interface HomePendingCounts {
  change_requests: number
  issues: number
  link_requests: number
  total: number
}

/** 主页聚合载荷（字段白名单见 ADR 0160 D2） */
export interface HomeSummary {
  workspace_count: number
  team_count: number
  pending: HomePendingCounts
  partial: boolean
}

export const homeApi = {
  /** 主页待办聚合（缓存 20s；失败不应阻断主页，调用方按可选信息处理） */
  summary: () => api.get<HomeSummary>('/v1/home/summary').then(r => r.data),
}

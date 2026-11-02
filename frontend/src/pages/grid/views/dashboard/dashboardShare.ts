/** dashboard 登录态只读分享的链接构造与展示态解析（ADR 0023 / 原 0077 P1）.
 *
 * 本模块只做两件纯前端的事：
 * - 生成无状态深链 `?view=<id>&mode=dashboard&present=1`（不落库、不带 token、不含权限）；
 * - 解析 `present=1` 是否命中一个当前用户可见的 dashboard 视图（**不做权限判定**，
 *   可见列表来自既有 `useTableViews`，权限仍由后端 `get_table_or_404` + `get_view_or_404` 决定）。
 *
 * 展示态命中失败时**绝不回落到默认视图**（ADR 0023 / 原 0077 D9 / C8）：回落会把「无权看 A」
 * 静默变成「看到了 B」，与视图可见性「不泄露存在性」的口径冲突。
 */

import type { View } from '@/api'

export interface DashboardShareInput {
  origin: string
  /** 数据表页面路径，形如 `/w/{wid}/tables/{tid}` */
  pathname: string
  viewId: number | string
}

/** 构造只读深链：仅保留视图 id、dashboard 模式与展示标记，转发结果稳定. */
export function buildDashboardShareUrl(input: DashboardShareInput): string {
  const params = new URLSearchParams({
    view: String(input.viewId),
    mode: 'dashboard',
    present: '1',
  })
  return `${input.origin}${input.pathname}?${params.toString()}`
}

export type PresentTarget =
  | { kind: 'normal' }
  | { kind: 'present'; view: View }
  | { kind: 'invalid'; reason: 'missing_view' | 'not_visible' | 'not_dashboard' }

/** 解析展示态目标；调用方须传入当前用户可见的视图列表.
 *
 * 判定顺序固定：非展示态 → 缺 `view` → 视图不可见 → 非 dashboard → 命中。
 */
export function resolvePresentTarget(
  views: View[],
  requestedViewId: string | null,
  present: boolean,
): PresentTarget {
  if (!present) return { kind: 'normal' }
  const requested = (requestedViewId ?? '').trim()
  if (!requested) return { kind: 'invalid', reason: 'missing_view' }
  const view = views.find((v) => String(v.id) === requested)
  if (!view) return { kind: 'invalid', reason: 'not_visible' }
  if (view.view_type !== 'dashboard') return { kind: 'invalid', reason: 'not_dashboard' }
  return { kind: 'present', view }
}

/** 复制当前 dashboard 的登录态只读链接，返回写入剪贴板的 URL. */
export async function copyDashboardShareLink(viewId: number | string): Promise<string> {
  const url = buildDashboardShareUrl({
    origin: window.location.origin,
    pathname: window.location.pathname,
    viewId,
  })
  await navigator.clipboard.writeText(url)
  return url
}

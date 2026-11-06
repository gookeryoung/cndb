/** 视图参数归一化（GridPage 与 hover 预取共用，ADR 0116 C7/C8）.
 *
 * 后端存储的 `filters` 兼容两种形态（list 与 dict），必须归一化成 list 后再进
 * `tableRecordsQueryKey`；预取与正式请求共用本模块，避免两边 key 构造漂移导致
 * 缓存不命中、多打一次行数据请求。
 */

import type { View } from '@/api'
import type { FilterRule } from './view-config/ViewConfigDialog'
import type { ViewMode } from './views/viewModes'

/** 有独立渲染模式的 view_type；其余（含空）回落表格 */
const MODE_VIEW_TYPES = new Set<string>([
  'tree', 'kanban', 'gallery', 'calendar', 'gantt', 'wbs', 'matrix', 'chart', 'flow', 'dashboard',
])

/** 视图类型 → 页面模式 */
export function viewModeOf(viewType: string | null | undefined): ViewMode {
  const vt = viewType ?? ''
  return MODE_VIEW_TYPES.has(vt) ? (vt as ViewMode) : 'grid'
}

/** 把后端存储的 filters（dict 或 list）归一化成 list 形式 */
export function normalizeFilters(raw: unknown): FilterRule[] {
  if (!raw) return []
  if (Array.isArray(raw)) {
    return raw
      .filter((r): r is Record<string, unknown> => typeof r === 'object' && r !== null)
      .map(r => ({
        field_name: String(r.field_name ?? ''),
        op: String(r.op ?? '='),
        ...(r.value !== undefined && r.value !== null ? { value: r.value } : {}),
      }))
  }
  if (typeof raw === 'object') {
    const result: FilterRule[] = []
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      if (k === '$query') continue  // 特殊 key 跳过
      if (typeof v === 'object' && v !== null && 'op' in v) {
        const vv = v as { op: string; value?: unknown }
        result.push({ field_name: k, op: vv.op, ...(vv.value !== undefined ? { value: vv.value } : {}) })
      } else {
        result.push({ field_name: k, op: '=', value: v })
      }
    }
    return result
  }
  return []
}

/** 首帧落地视图：URL 深链 > 默认视图 > 第一个（与 GridPage 的匹配顺序一致） */
export function resolveLandingView(views: View[], viewParam?: string | null): View | null {
  if (viewParam) {
    const hit = views.find(v => String(v.id) === viewParam)
    if (hit) return hit
  }
  return views.find(v => v.is_default) ?? views[0] ?? null
}

/** 全局筛选取值与 `{{global.x}}` 占位符解析（ADR 0023 P3）.
 *
 * 与后端 `dashboard_data.resolve_query_globals` 同口径：取值后统一改写 widget 的
 * `query.filters`，缺值的条件直接丢弃并计入 `unapplied`；渲染层不再拼条件。
 */

import { GLOBAL_REF_RE } from './dashboardModel'
import type { DashboardFilter, DashboardQuery } from './dashboardModel'

/** 全局筛选值（id → 值）；date_range 为 `[start, end]`，select 为数组，search 为字符串 */
export type DashboardGlobals = Record<string, unknown>

/** 过滤值是否引用全局筛选 */
export function hasGlobalRef(value: unknown): boolean {
  if (typeof value === 'string') return GLOBAL_REF_RE.test(value)
  if (Array.isArray(value)) return value.some(hasGlobalRef)
  return false
}

/** date_range 请求形态（`{from,to}`）→ 过滤值形态（二元数组） */
function toFilterValue(value: unknown): unknown {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    if ('from' in record || 'to' in record || 'start' in record || 'end' in record) {
      const start = record.from ?? record.start
      const end = record.to ?? record.end
      return [start ?? null, end ?? null]
    }
  }
  return value
}

/** 替换单个过滤值中的占位符；返回 (新值, 是否全部解析成功) */
export function resolveGlobalValue(value: unknown, globals: DashboardGlobals): [unknown, boolean] {
  if (typeof value === 'string') {
    const match = GLOBAL_REF_RE.exec(value)
    if (!match) return [value, true]
    const resolved = globals[match[1]]
    if (resolved == null || resolved === '' || (Array.isArray(resolved) && resolved.length === 0)) {
      return [null, false]
    }
    return [toFilterValue(resolved), true]
  }
  if (Array.isArray(value)) {
    const items: unknown[] = []
    for (const item of value) {
      const [resolved, ok] = resolveGlobalValue(item, globals)
      if (!ok) return [null, false]
      items.push(resolved)
    }
    return [items, true]
  }
  return [value, true]
}

/** 解析 widget 查询中的全局筛选占位符；未提供值的条件丢弃并计数 */
export function resolveQueryGlobals(
  query: DashboardQuery,
  globals: DashboardGlobals,
): { query: DashboardQuery; unapplied: number } {
  if (!query.filters.length) return { query, unapplied: 0 }
  const filters: DashboardFilter[] = []
  let unapplied = 0
  for (const rule of query.filters) {
    const [value, ok] = resolveGlobalValue(rule.value, globals)
    if (!ok) {
      unapplied += 1
      continue
    }
    filters.push({ ...rule, value })
  }
  return { query: { ...query, filters }, unapplied }
}

/** 表格视图状态的 sessionStorage 快照 —— 冷进表首帧种子化（ADR 0116 C8 / D9）.
 *
 * 目的：GridPage 挂载时 store 尚未归属当前表，若先按空筛选请求行数据，
 * 等默认视图 / 上次视图加载后再按筛选重发，会多出一次行请求并闪现未筛选列表。
 * 这里按 `wid/tid` 记录上一次的视图参数，首帧命中时直接按快照请求，只发一次。
 *
 * 约定：
 *  - 仅 sessionStorage（标签页级），不参与持久化偏好，关闭标签页即失效；
 *  - 结构变更时整键丢弃（版本号写在 key 里），不做迁移；
 *  - 隐私模式 / 配额满 / 数据损坏一律静默退化，不抛错、不阻塞首屏；
 *  - 最多保留 20 张表，避免长会话无限增长。
 */

import type { FilterRule, SortRule } from '@/pages/grid/view-config/ViewConfigDialog'
import type { ViewMode } from '@/pages/grid/views/viewModes'

export const GRID_VIEW_STATE_KEY = 'cndb_grid_view_state_v1'

const MAX_TABLE_ENTRIES = 20

export interface GridViewSnapshot {
  activeViewId: number | string | null
  viewFilters: FilterRule[]
  viewSortings: SortRule[]
  viewFilterLogic: 'AND' | 'OR'
  mode: ViewMode
  offset: number
  limit: number
}

const isRuleArray = (value: unknown): value is Record<string, unknown>[] =>
  Array.isArray(value) && value.every(item => typeof item === 'object' && item !== null)

/** 读取指定表的快照；未命中 / 损坏 / storage 不可用时返回 null */
export function readGridViewSnapshot(tableKey: string): GridViewSnapshot | null {
  try {
    const raw = sessionStorage.getItem(GRID_VIEW_STATE_KEY)
    if (!raw) return null
    const store = JSON.parse(raw) as Record<string, unknown>
    const entry = store?.[tableKey]
    if (typeof entry !== 'object' || entry === null) return null
    const snapshot = entry as Record<string, unknown>
    if (!isRuleArray(snapshot.viewFilters) || !isRuleArray(snapshot.viewSortings)) return null
    if (typeof snapshot.mode !== 'string') return null
    if (typeof snapshot.offset !== 'number' || typeof snapshot.limit !== 'number') return null
    return {
      activeViewId:
        typeof snapshot.activeViewId === 'number' || typeof snapshot.activeViewId === 'string'
          ? snapshot.activeViewId
          : null,
      viewFilters: snapshot.viewFilters as unknown as FilterRule[],
      viewSortings: snapshot.viewSortings as unknown as SortRule[],
      viewFilterLogic: snapshot.viewFilterLogic === 'OR' ? 'OR' : 'AND',
      mode: snapshot.mode as ViewMode,
      offset: snapshot.offset,
      limit: snapshot.limit,
    }
  } catch {
    return null
  }
}

/** 写入指定表的快照；失败（隐私模式 / 配额满）静默忽略 */
export function writeGridViewSnapshot(tableKey: string, snapshot: GridViewSnapshot): void {
  try {
    const raw = sessionStorage.getItem(GRID_VIEW_STATE_KEY)
    const store = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    const next: Record<string, unknown> = {
      ...(typeof store === 'object' && store !== null ? store : {}),
      [tableKey]: snapshot,
    }
    const keys = Object.keys(next)
    if (keys.length > MAX_TABLE_ENTRIES) {
      for (const key of keys.slice(0, keys.length - MAX_TABLE_ENTRIES)) delete next[key]
    }
    sessionStorage.setItem(GRID_VIEW_STATE_KEY, JSON.stringify(next))
  } catch {
    /* storage 不可用时退化为原行为 */
  }
}

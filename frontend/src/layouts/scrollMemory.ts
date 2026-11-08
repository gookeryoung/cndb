/** 内容区滚动位置记忆 —— 会话级（sessionStorage），按 pathname 记录.
 *
 * 用途：返回列表页 / 刷新当前页时恢复内容区滚动位置，避免每次都回到顶部。
 * 约定：只记路径不含 query（同一路径的筛选变化不应互相覆盖）；最多保留 50 条。
 */

export const SCROLL_STORAGE_KEY = 'cndb_scroll_positions_v1'

const MAX_ENTRIES = 50

function readStore(): Record<string, number> {
  try {
    const raw = sessionStorage.getItem(SCROLL_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' ? parsed as Record<string, number> : {}
  } catch {
    return {}
  }
}

/** 读取某路径上次的滚动位置（未记录 / 损坏时返回 0） */
export function readScrollTop(pathname: string): number {
  const top = readStore()[pathname]
  return typeof top === 'number' && Number.isFinite(top) && top > 0 ? top : 0
}

/** 记录某路径的滚动位置；失败静默忽略 */
export function writeScrollTop(pathname: string, top: number): void {
  const store = readStore()
  if (top > 0) store[pathname] = top
  else delete store[pathname]

  const keys = Object.keys(store)
  if (keys.length > MAX_ENTRIES) {
    for (const key of keys.slice(0, keys.length - MAX_ENTRIES)) delete store[key]
  }

  try {
    sessionStorage.setItem(SCROLL_STORAGE_KEY, JSON.stringify(store))
  } catch {
    /* storage 不可用时退化为不记忆 */
  }
}

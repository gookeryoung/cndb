/** 主页自定义展示顺序的纯函数（ADR 0021 决策 D3）.
 *
 * 工作区：已收藏（pinned）分组优先；组内按 `preferences.workspace_order` 排名，
 * 未登记的 id 按原 id 兜底 —— 与后端 `pinned → id` 的兜底口径保持一致。
 * 收藏视图：展示顺序即 `preferences.favorite_views` 列表顺序，无分组。
 */

export interface SortableWorkspace {
  id: number | string
  pinned?: boolean | null
}

/** 把有序 id 列表转成「id → 名次」映射；非正整数与重复项忽略（与后端 normalize_ids 同口径） */
export function buildRankMap(order: Array<number | string> | null | undefined): Map<number, number> {
  const rank = new Map<number, number>()
  for (const raw of order ?? []) {
    const id = Number(raw)
    if (!Number.isInteger(id) || id <= 0 || rank.has(id)) continue
    rank.set(id, rank.size)
  }
  return rank
}

/** 工作区排序：pinned 分组优先 → 自定义顺序 → id；返回新数组，不改入参 */
export function sortWorkspaces<T extends SortableWorkspace>(
  list: readonly T[],
  order: Array<number | string> | null | undefined,
): T[] {
  const rank = buildRankMap(order)
  const unranked = Number.MAX_SAFE_INTEGER
  return [...list].sort((a, b) => {
    const pinnedDelta = Number(!!b.pinned) - Number(!!a.pinned)
    if (pinnedDelta !== 0) return pinnedDelta
    const rankDelta = (rank.get(Number(a.id)) ?? unranked) - (rank.get(Number(b.id)) ?? unranked)
    if (rankDelta !== 0) return rankDelta
    return Number(a.id) - Number(b.id)
  })
}

/** 按当前展示顺序扁平化「已收藏组 + 其他组」，作为一次全量提交的 id 列表 */
export function flattenWorkspaceOrder(
  starredIds: Array<number | string>,
  otherIds: Array<number | string>,
): number[] {
  return [...starredIds, ...otherIds].map(Number)
}

/** Grid 数据装配 hook — 派生生效筛选/排序/分页参数并拉取行数据（从 GridPage 抽出）. */

import { useMemo } from 'react'
import { useTableRecords } from '@/api/hooks'

interface UseGridDataParams {
  wid: string | undefined
  tid: string | undefined
  mode: string
  limit: number
  offset: number
  viewFilters: unknown[]
  viewSortings: unknown[]
  viewFilterLogic: 'AND' | 'OR'
  searchQuery: string
}

/** 非 grid 视图需要数据做分组/聚合。降低上限到 2000（覆盖 99% 使用场景，避免每次切换拉 5000 条的网络+渲染压力） */
export const VIEW_FETCH_ALL_LIMIT = 2000

export function useGridData({ wid, tid, mode, limit, offset, viewFilters, viewSortings, viewFilterLogic, searchQuery }: UseGridDataParams) {
  // 当前生效的筛选条件（视图筛选 + 全局关键词）
  const effectiveFilters = useMemo(() => {
    const list: Array<Record<string, unknown>> = [...(viewFilters as unknown as Array<Record<string, unknown>>)]
    if (searchQuery.trim()) list.push({ field_name: '__query__', op: 'contains', value: searchQuery.trim() })
    return list.length ? list : undefined
  }, [viewFilters, searchQuery])

  // 当前生效的排序条件
  const sortsParam = useMemo(() => {
    return viewSortings.length ? (viewSortings as unknown as Array<Record<string, unknown>>) : undefined
  }, [viewSortings])

  const effectiveLimit = mode === 'grid' ? limit : VIEW_FETCH_ALL_LIMIT
  const effectiveOffset = mode === 'grid' ? offset : 0

  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 } } = useTableRecords(
    wid!, tid!, mode,
    {
      offset: effectiveOffset,
      limit: effectiveLimit,
      filters: effectiveFilters,
      sorts: sortsParam,
      filter_logic: viewFilterLogic,
    },
  )

  return { effectiveFilters, sortsParam, effectiveLimit, effectiveOffset, rowList }
}

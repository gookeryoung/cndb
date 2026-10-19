/** Grid 数据装配 hook — 派生生效筛选/排序/分页参数并拉取行数据（从 GridPage 抽出）. */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTableRecords } from '@/api/hooks'
import { changeRequestsApi } from '@/api'
import type { ChangeRequest } from '@/api'

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

  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 }, isFetching } = useTableRecords(
    wid!, tid!, mode,
    {
      offset: effectiveOffset,
      limit: effectiveLimit,
      filters: effectiveFilters,
      sorts: sortsParam,
      filter_logic: viewFilterLogic,
    },
  )

  return { effectiveFilters, sortsParam, effectiveLimit, effectiveOffset, rowList, isFetching }
}

/**
 * 编辑中状态查询（默认启用）。
 *
 * 走 group_by=row 聚合端点一次拉取全部 open 申请的行组，
 * 返回 rowId → 申请 的 Map 供行级锁定与编辑中标识（避免逐条取详情的 N+1）；
 * 提交/合并/关闭申请后 invalidate，不做逐行请求。
 */
export function usePendingChanges(wid: string | undefined, tid: string | undefined, enabled = true) {
  const tableKey = `${wid}/${tid}`
  return useQuery<Map<string, ChangeRequest>>({
    queryKey: ['pending-changes', tableKey],
    queryFn: async () => {
      const page = await changeRequestsApi.listGrouped(wid!, tid!, 'open')
      const map = new Map<string, ChangeRequest>()
      for (const group of page.groups ?? []) {
        const latest = group.requests[0]
        if (latest) map.set(String(group.row_id), latest)
      }
      return map
    },
    enabled: enabled && !!wid && !!tid,
    staleTime: 10_000,
  })
}

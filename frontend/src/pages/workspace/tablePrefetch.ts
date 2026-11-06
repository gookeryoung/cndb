/** 表行 hover 预取 —— 表详情 / 视图 / 首帧行数据 / GridPage chunk（ADR 0116 C7 / D8）.
 *
 * 点击进表是高频路径。hover 停留 200ms（150–300ms 窗口）后并行预取：
 *   - `['table', wid/tid]`（useTable）
 *   - `['table-views', wid/tid]`（useTableViews）
 *   - 首帧行数据（queryKey 由 useTableRecords 的唯一构造器生成，参数优先取 sessionStorage 快照）
 *   - `GridPage` 页面 chunk
 *
 * 扫过列表不产生请求风暴：离开行立即取消尚未触发的定时器。
 * 预取失败（离线 / 401 / 404）静默，不影响正式请求的错误态。
 */

import { useMemo } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import { tableApi, viewApi, recordApi } from '@/api'
import type { View } from '@/api'
import { tableRecordsQueryKey } from '@/api/hooks'
import { useTableSettingsStore } from '@/store'
import { readGridViewSnapshot } from '@/pages/grid/gridViewSeed'
import { normalizeFilters, resolveLandingView, viewModeOf } from '@/pages/grid/gridViewParams'

export const TABLE_HOVER_PREFETCH_DELAY_MS = 200

/** 预取该表进入首屏所需的全部资源（不读组件状态，便于单测直接调用） */
export function prefetchTableBundle(
  queryClient: QueryClient,
  wid: string,
  tid: string,
): void {
  const tableKey = `${wid}/${tid}`
  const snapshot = readGridViewSnapshot(tableKey)

  const prefetchRecords = (params: {
    offset: number
    limit: number
    filters?: Record<string, unknown>[]
    sorts?: Record<string, unknown>[]
    filter_logic?: 'AND' | 'OR'
    mode: string
  }) => {
    void queryClient
      .prefetchQuery({
        queryKey: tableRecordsQueryKey(wid, tid, params.mode, params),
        queryFn: () => recordApi.list(wid, tid, params),
        staleTime: 10_000,
      })
      .catch(() => undefined)
  }

  void queryClient
    .prefetchQuery({
      queryKey: ['table', tableKey],
      queryFn: () => tableApi.get(wid, tid),
      staleTime: 60_000,
    })
    .catch(() => undefined)
  const viewsPromise = queryClient
    .prefetchQuery({
      queryKey: ['table-views', tableKey],
      queryFn: () => viewApi.list(wid, tid),
      staleTime: 60_000,
    })
    .catch(() => undefined)

  if (snapshot) {
    // 有快照：直接按上次的视图参数预取首帧行，点击进表即命中缓存
    prefetchRecords({
      mode: snapshot.mode,
      offset: snapshot.offset,
      limit: snapshot.limit,
      filters: snapshot.viewFilters as unknown as Record<string, unknown>[],
      sorts: snapshot.viewSortings as unknown as Record<string, unknown>[],
      filter_logic: snapshot.viewFilterLogic,
    })
  } else {
    // 无快照：首帧行参数取决于落地视图，等视图列表回来再按同一套归一化参数预取，
    // 否则会预取一份空筛选缓存，正式首帧仍要重发（ADR 0116 C7 / C8）
    void viewsPromise.then(() => {
      const views = queryClient.getQueryData<View[]>(['table-views', tableKey]) ?? []
      const view = resolveLandingView(views, null)
      prefetchRecords({
        mode: viewModeOf(view?.view_type),
        offset: 0,
        limit: useTableSettingsStore.getState().defaultPageSize,
        filters: normalizeFilters(view?.filters) as unknown as Record<string, unknown>[],
        sorts: (Array.isArray(view?.sortings) ? view!.sortings : []) as unknown as Record<string, unknown>[],
        filter_logic: (view?.filter_type ?? 'AND') as 'AND' | 'OR',
      })
    })
  }

  void import('@/pages/grid/GridPage').catch(() => undefined)
}

export interface TableHoverPrefetch {
  /** 指针进入表行：防抖后触发预取 */
  onEnter: (tid: string | number) => void
  /** 指针离开表行：取消尚未触发的预取 */
  onLeave: (tid: string | number) => void
}

/** 每行独立的防抖定时器：扫过列表时只保留最后停留的那一行 */
export function useTableHoverPrefetch(
  queryClient: QueryClient,
  wid: string | undefined,
  delayMs: number = TABLE_HOVER_PREFETCH_DELAY_MS,
  run: (queryClient: QueryClient, wid: string, tid: string) => void = prefetchTableBundle,
): TableHoverPrefetch {
  return useMemo(() => {
    const timers = new Map<string, number>()
    const clear = (tid: string | number) => {
      const key = String(tid)
      const timer = timers.get(key)
      if (timer != null) {
        window.clearTimeout(timer)
        timers.delete(key)
      }
    }
    // 指针同一时刻只停在一行：进入新行即取消其它行的待触发预取，扫列表不产生请求风暴
    const clearAll = () => {
      for (const timer of timers.values()) window.clearTimeout(timer)
      timers.clear()
    }
    return {
      onEnter: (tid) => {
        if (!wid) return
        clearAll()
        timers.set(
          String(tid),
          window.setTimeout(() => {
            timers.delete(String(tid))
            run(queryClient, wid, String(tid))
          }, delayMs),
        )
      },
      onLeave: (tid) => clear(tid),
    }
  }, [queryClient, wid, delayMs, run])
}

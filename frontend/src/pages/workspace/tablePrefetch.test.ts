/** tablePrefetch 单元测试 —— 防抖窗口、离开取消、queryKey 与 useTableRecords 一致（ADR 0116 C7）. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient } from '@tanstack/react-query'
import { tableApi, viewApi, recordApi } from '@/api'
import { tableRecordsQueryKey } from '@/api/hooks'
import { useTableSettingsStore } from '@/store'
import { TABLE_HOVER_PREFETCH_DELAY_MS, prefetchTableBundle, useTableHoverPrefetch } from './tablePrefetch'
import { GRID_VIEW_STATE_KEY } from '@/pages/grid/gridViewSeed'

vi.mock('@/pages/grid/GridPage', () => ({ default: () => null }))

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('prefetchTableBundle', () => {
  it('无快照时先取视图，再按落地视图参数预取首帧行（queryKey 与 useTableRecords 一致）', async () => {
    vi.spyOn(tableApi, 'get').mockResolvedValue({} as never)
    vi.spyOn(viewApi, 'list').mockResolvedValue([])
    vi.spyOn(recordApi, 'list').mockResolvedValue({ items: [], total: 0, offset: 0, limit: 0 })
    const queryClient = makeQueryClient()
    const prefetch = vi.spyOn(queryClient, 'prefetchQuery')

    prefetchTableBundle(queryClient, '1', '2')

    const expectedRecordsKey = tableRecordsQueryKey('1', '2', 'grid', {
      offset: 0,
      limit: useTableSettingsStore.getState().defaultPageSize,
    })
    await vi.waitFor(() => {
      const keys = prefetch.mock.calls.map((call) => call[0].queryKey)
      expect(keys).toContainEqual(['table', '1/2'])
      expect(keys).toContainEqual(['table-views', '1/2'])
      expect(keys).toContainEqual([...expectedRecordsKey])
      expect(recordApi.list).toHaveBeenCalledWith(
        '1',
        '2',
        expect.objectContaining({ offset: 0, limit: useTableSettingsStore.getState().defaultPageSize }),
      )
    })
  })

  it('命中 sessionStorage 快照时直接按快照参数预取首帧行，不等视图列表', () => {
    const snapshot = {
      activeViewId: 3,
      viewFilters: [{ field_name: 'status', op: '=', value: 'open' }],
      viewSortings: [{ field_name: 'created_at', direction: 'desc' }],
      viewFilterLogic: 'AND' as const,
      mode: 'grid' as const,
      offset: 0,
      limit: 20,
    }
    sessionStorage.setItem(GRID_VIEW_STATE_KEY, JSON.stringify({ '1/2': snapshot }))
    vi.spyOn(tableApi, 'get').mockResolvedValue({} as never)
    vi.spyOn(viewApi, 'list').mockResolvedValue([])
    vi.spyOn(recordApi, 'list').mockResolvedValue({ items: [], total: 0, offset: 0, limit: 0 })
    const queryClient = makeQueryClient()
    const prefetch = vi.spyOn(queryClient, 'prefetchQuery')

    prefetchTableBundle(queryClient, '1', '2')

    const expectedRecordsKey = tableRecordsQueryKey('1', '2', 'grid', {
      offset: 0,
      limit: 20,
      filters: snapshot.viewFilters,
      sorts: snapshot.viewSortings,
      filter_logic: 'AND',
    })
    expect(prefetch.mock.calls.map((call) => call[0].queryKey)).toContainEqual([...expectedRecordsKey])
    expect(recordApi.list).toHaveBeenCalledWith('1', '2', expect.objectContaining({ limit: 20 }))
  })

  it('预取失败静默，不抛错', () => {
    const queryClient = makeQueryClient()
    vi.spyOn(queryClient, 'prefetchQuery').mockRejectedValue(new Error('offline'))
    expect(() => prefetchTableBundle(queryClient, '1', '2')).not.toThrow()
  })
})

describe('useTableHoverPrefetch 防抖', () => {
  it('默认 150–300ms 窗口内只触发一次', () => {
    vi.useFakeTimers()
    const run = vi.fn()
    const { result } = renderHook(() =>
      useTableHoverPrefetch(makeQueryClient(), '1', TABLE_HOVER_PREFETCH_DELAY_MS, run),
    )
    expect(TABLE_HOVER_PREFETCH_DELAY_MS).toBeGreaterThanOrEqual(150)
    expect(TABLE_HOVER_PREFETCH_DELAY_MS).toBeLessThanOrEqual(300)

    result.current.onEnter('t-1')
    vi.advanceTimersByTime(TABLE_HOVER_PREFETCH_DELAY_MS - 1)
    expect(run).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run.mock.calls[0]![1]).toBe('1')
    expect(run.mock.calls[0]![2]).toBe('t-1')
  })

  it('离开行立即取消尚未触发的预取', () => {
    vi.useFakeTimers()
    const run = vi.fn()
    const { result } = renderHook(() =>
      useTableHoverPrefetch(makeQueryClient(), '1', TABLE_HOVER_PREFETCH_DELAY_MS, run),
    )
    result.current.onEnter('t-1')
    vi.advanceTimersByTime(TABLE_HOVER_PREFETCH_DELAY_MS - 10)
    result.current.onLeave('t-1')
    vi.advanceTimersByTime(1000)
    expect(run).not.toHaveBeenCalled()
  })

  it('扫过列表时只保留最后停留的行（不产生请求风暴）', () => {
    vi.useFakeTimers()
    const run = vi.fn()
    const { result } = renderHook(() =>
      useTableHoverPrefetch(makeQueryClient(), '1', TABLE_HOVER_PREFETCH_DELAY_MS, run),
    )
    result.current.onEnter('a')
    result.current.onEnter('b')
    result.current.onEnter('c')
    vi.advanceTimersByTime(TABLE_HOVER_PREFETCH_DELAY_MS)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run.mock.calls[0]![2]).toBe('c')
  })

  it('未归属工作区时不预取', () => {
    vi.useFakeTimers()
    const run = vi.fn()
    const { result } = renderHook(() =>
      useTableHoverPrefetch(makeQueryClient(), undefined, TABLE_HOVER_PREFETCH_DELAY_MS, run),
    )
    result.current.onEnter('a')
    vi.advanceTimersByTime(1000)
    expect(run).not.toHaveBeenCalled()
  })
})

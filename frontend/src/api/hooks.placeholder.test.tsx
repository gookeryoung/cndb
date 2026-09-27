/**
 * useTableRecords placeholderData 行为回归 —— 切表加载态设计（.trae/designs/table-switch-loading.md）.
 *
 * 语义：
 * 1. 同表参数变化（翻页 offset）→ 新请求挂起期间保留上一份数据（isPlaceholderData），
 *    isFetching 驱动 Table loading 遮罩，不出现空态闪现。
 * 2. 跨表切换（tableKey 变化）→ 请求期间 data 为 undefined，旧表数据不得配新表列。
 */

import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTableRecords } from './hooks'

vi.mock('@/api', () => ({
  tableApi: { get: vi.fn(), references: vi.fn() },
  recordApi: { list: vi.fn(), update: vi.fn(), bulkDelete: vi.fn() },
  viewApi: { list: vi.fn() },
  auditApi: { list: vi.fn() },
}))

import { recordApi } from '@/api'
import type { RowListResponse } from '@/api'

/** 两行样例数据 —— 断言只关心条数，与字段结构无关 */
function makeRows(): RowListResponse {
  return {
    items: [{ id: 1, 姓名: '张三' }, { id: 2, 姓名: '李四' }] as unknown as RowListResponse['items'],
    total: 2,
    offset: 0,
    limit: 25,
  }
}

/** 独立 QueryClient —— 保留默认 gcTime（placeholderData 依赖观察者上一份结果），关闭重试保证确定性 */
function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { Wrapper }
}

describe('useTableRecords placeholderData —— 切表加载态', () => {
  it('同表翻页：新请求挂起期间保留上一份数据（isPlaceholderData=true）', async () => {
    let calls = 0
    vi.mocked(recordApi.list).mockImplementation(() => {
      calls += 1
      if (calls === 1) return Promise.resolve(makeRows())
      return new Promise(() => { })  // 第二次请求（offset=25）永久挂起，观察占位行为
    })

    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      ({ offset }: { offset: number }) => useTableRecords('10', '100', 'grid', { offset, limit: 25 }),
      { wrapper: Wrapper, initialProps: { offset: 0 } },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toHaveLength(2)

    // 同表 offset 变化 → queryKey 变化但 tableKey（queryKey[1]）相同 → placeholder 保留旧数据
    rerender({ offset: 25 })
    await waitFor(() => expect(result.current.isFetching).toBe(true))
    expect(result.current.data?.items).toHaveLength(2)
    expect(result.current.isPlaceholderData).toBe(true)
  })

  it('跨表切换：请求期间数据为 undefined，不沿用旧表数据', async () => {
    vi.mocked(recordApi.list).mockImplementation((_wid, tid) =>
      String(tid) === '100'
        ? Promise.resolve(makeRows())
        : new Promise(() => { }),  // 新表（tid=200）请求永久挂起
    )

    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      ({ tid }: { tid: string }) => useTableRecords('10', tid, 'grid', { offset: 0, limit: 25 }),
      { wrapper: Wrapper, initialProps: { tid: '100' } },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toHaveLength(2)

    // 切到另一张表 → tableKey 变化 → placeholder 返回 undefined，走正常 loading
    rerender({ tid: '200' })
    await waitFor(() => expect(result.current.isFetching).toBe(true))
    expect(result.current.data).toBeUndefined()
    expect(result.current.isSuccess).toBe(false)
  })
})

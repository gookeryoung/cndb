/**
 * api/hooks React Query hooks 测试 —— 查询与乐观更新 mutation.
 *
 * 覆盖：
 * 1. 查询 hooks（useTable/useTableViews/useTableRecords/
 *    useRowAudit/useRowReferences）成功路径与 enabled 守卫
 * 2. useTableRecords 过滤参数序列化到请求 URL
 * 3. useUpdateRowOptimistic：乐观写 cache 成功 / 失败回滚
 * 4. useDeleteRowsOptimistic：乐观删除成功
 *
 * 注：mutation 用例用独立 QueryClient 手工 seed cache；
 *    GET records 用 delay: 'infinite' 挂起，避免 onSettled 的 invalidate
 *    refetch 覆盖乐观结果，保证断言确定性。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  useDeleteRowsOptimistic,
  useRowAudit,
  useRowReferences,
  useTable,
  useTableRecords,
  useTableViews,
  useUpdateRowOptimistic,
} from './hooks'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { renderHookProviders } from '@/test/render-providers'
import { server, mockRecords } from '@/test/msw'
import type { RowListResponse } from '@/api'

// ─────────────── 查询 hooks ───────────────

describe('查询 hooks', () => {
  it('useTable 返回表详情（MSW 局部 handler）', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/tables/100', () =>
        HttpResponse.json({
          id: 100, name: '客户表', description: '',
          fields: [{ id: 1000, name: '姓名', field_type: 'text', order: 0 }],
        })),
    )
    const { result } = renderHookProviders(() => useTable('10', '100'))

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.name).toBe('客户表')
  })

  it('useTable / useTableViews / useTableRecords 在 wid/tid 为空时不发起请求', async () => {
    const { result: table } = renderHookProviders(() => useTable('', ''))
    const { result: views } = renderHookProviders(() => useTableViews('', ''))
    const { result: records } = renderHookProviders(() => useTableRecords('', '', 'grid', {}))

    await waitFor(() => {
      expect(table.current.fetchStatus).toBe('idle')
      expect(views.current.fetchStatus).toBe('idle')
      expect(records.current.fetchStatus).toBe('idle')
    })
    expect(table.current.data).toBeUndefined()
  })

  it('useTableViews 返回视图列表（默认 handler）', async () => {
    const { result } = renderHookProviders(() => useTableViews('10', '100'))

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data?.[0]?.name).toBe('全部数据')
  })

  it('useTableRecords 返回行数据（默认 handler）', async () => {
    const { result } = renderHookProviders(() =>
      useTableRecords('10', '100', 'grid', { offset: 0, limit: 25 }))

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.total).toBe(2)
    expect(result.current.data?.items).toHaveLength(2)
  })

  it('useTableRecords 将 filters/sorts/filter_logic 序列化进请求参数', async () => {
    let captured = ''
    server.use(
      http.get('/api/v1/workspaces/10/tables/100/records', ({ request }) => {
        captured = new URL(request.url).search
        return HttpResponse.json(mockRecords)
      }),
    )
    const filters = [{ op: 'contains', field: '姓名', value: '张' }]
    const sorts = [{ field: 'id', direction: 'asc' }]
    const { result } = renderHookProviders(() =>
      useTableRecords('10', '100', 'grid', { filters, sorts, filter_logic: 'OR' }))

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // axios 对 : , [ ] 等字符有自己的编码策略，解析 search 后比对 JSON 更稳
    const search = new URLSearchParams(captured)
    expect(JSON.parse(search.get('filters') ?? 'null')).toEqual(filters)
    expect(JSON.parse(search.get('sorts') ?? 'null')).toEqual(sorts)
    expect(search.get('filter_logic')).toBe('OR')
  })

  it('useRowAudit 返回审计记录；rowId 为空时不发请求', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/tables/100/audit', () =>
        HttpResponse.json([{ id: 1, action: 'update', created_at: '2026-01-01' }])),
    )
    const { result } = renderHookProviders(() => useRowAudit('10', '100', 1))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)

    const { result: idle } = renderHookProviders(() => useRowAudit('10', '100', undefined))
    await waitFor(() => expect(idle.current.fetchStatus).toBe('idle'))
  })

  it('useRowReferences 返回引用列表（MSW 局部 handler）', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/tables/100/records/1/references', () =>
        HttpResponse.json([{ id: 9, table_name: '订单表', row_id: 5 }])),
    )
    const { result } = renderHookProviders(() => useRowReferences('10', '100', 1))

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
  })
})

// ─────────────── 乐观更新 mutations ───────────────

/** mutation 专用包装：独立 QueryClient（保留默认 gcTime，避免手工 seed 被 GC）+ ThemeProvider（提供 AntApp message） */
function makeMutationWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ThemeProvider>{children}</ThemeProvider>
    </QueryClientProvider>
  )
  return { qc, Wrapper }
}

/** seed 一个 table-records 缓存条目（与 useTableRecords 的 queryKey 结构一致） */
function seedRecords(qc: QueryClient, items: Array<Record<string, unknown>>) {
  const key = ['table-records', '10/100', 'grid', 0, 25, '', '', 'AND']
  qc.setQueryData<RowListResponse>(key, {
    items: items as RowListResponse['items'],
    total: items.length,
    offset: 0,
    limit: 25,
  })
  return key
}

describe('useUpdateRowOptimistic', () => {
  it('更新成功：cache 乐观写入新值', async () => {
    // 挂起 GET records，防止 onSettled invalidate 的 refetch 覆盖乐观结果
    server.use(
      http.get('/api/v1/workspaces/10/tables/100/records', async () => {
        await delay('infinite')
        return HttpResponse.json(mockRecords)
      }),
      http.patch('/api/v1/workspaces/10/tables/100/records/1', () =>
        HttpResponse.json({ id: 1, 姓名: '李四' })),
    )
    const { qc, Wrapper } = makeMutationWrapper()
    const key = seedRecords(qc, [{ id: 1, 姓名: '张三' }, { id: 2, 姓名: '王五' }])

    const { result } = renderHook(() => useUpdateRowOptimistic('10', '100'), { wrapper: Wrapper })
    result.current.mutate({ rowId: 1, fieldName: '姓名', value: '李四' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const cached = qc.getQueryData<RowListResponse>(key)
    expect(cached?.items[0]).toMatchObject({ id: 1, 姓名: '李四' })
    expect(cached?.items[1]).toMatchObject({ id: 2, 姓名: '王五' })
  })

  it('更新失败：cache 回滚到更新前数据', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/tables/100/records', async () => {
        await delay('infinite')
        return HttpResponse.json(mockRecords)
      }),
      http.patch('/api/v1/workspaces/10/tables/100/records/1', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    const { qc, Wrapper } = makeMutationWrapper()
    const key = seedRecords(qc, [{ id: 1, 姓名: '张三' }])

    const { result } = renderHook(() => useUpdateRowOptimistic('10', '100'), { wrapper: Wrapper })
    result.current.mutate({ rowId: 1, fieldName: '姓名', value: '被改掉' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    const cached = qc.getQueryData<RowListResponse>(key)
    expect(cached?.items[0]).toMatchObject({ id: 1, 姓名: '张三' })
  })
})

describe('useDeleteRowsOptimistic', () => {
  it('删除成功：被删行从 cache 移除且 total 递减', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/tables/100/records', async () => {
        await delay('infinite')
        return HttpResponse.json(mockRecords)
      }),
      http.post('/api/v1/workspaces/10/tables/100/records/bulk-delete', () =>
        HttpResponse.json({ deleted: 1 })),
    )
    const { qc, Wrapper } = makeMutationWrapper()
    const key = seedRecords(qc, [{ id: 1, 姓名: '张三' }, { id: 2, 姓名: '李四' }])

    const { result } = renderHook(() => useDeleteRowsOptimistic('10', '100'), { wrapper: Wrapper })
    result.current.mutate([2])

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const cached = qc.getQueryData<RowListResponse>(key)
    expect(cached?.items).toHaveLength(1)
    expect(cached?.items[0]).toMatchObject({ id: 1 })
    expect(cached?.total).toBe(1)
  })
})

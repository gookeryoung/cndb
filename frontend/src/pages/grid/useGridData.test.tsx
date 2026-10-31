/** usePendingChanges 单测 —— ADR 0005 M4：行级「编辑中」标识收敛到 group_by=row 聚合端点.
 *
 * 断言三点：
 * 1. 挂载即调用一次 `GET /change-requests?scope=open&group_by=row`（聚合端点）；
 * 2. 全程零次申请详情 `GET /change-requests/{id}`（消除逐条 get 的 N+1）；
 * 3. 返回 Map 为 rowId → 组内最新申请（requests[0]），create-only 的 ungrouped 不进 Map。
 */

import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'

import { server } from '@/test/msw'
import { usePendingChanges } from './useGridData'
import type { ChangeRequest, ChangeRowGroupPage } from '@/api'

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

const req = (id: number, createdAt: string): ChangeRequest => ({
  id,
  workspace_id: 10,
  table_id: 100,
  title: `申请 ${id}`,
  description: '',
  status: 'open',
  stale: false,
  submitted_by_id: 7,
  reviewed_by_id: null,
  created_at: createdAt,
})

const groupedPage: ChangeRowGroupPage = {
  groups: [
    {
      row_id: 1,
      row_values: { id: 1, 姓名: '张三' },
      row_missing: false,
      // 组内按 created_at 倒序：最新在前
      requests: [req(2, '2026-10-31T10:00:00'), req(1, '2026-10-30T10:00:00')],
      conflict_fields: [],
      drift_fields: [],
      has_conflict: false,
      has_drift: false,
      latest_created_at: '2026-10-31T10:00:00',
    },
    {
      row_id: 2,
      row_values: { id: 2, 姓名: '李四' },
      row_missing: false,
      requests: [req(3, '2026-10-29T10:00:00')],
      conflict_fields: [],
      drift_fields: [],
      has_conflict: false,
      has_drift: false,
      latest_created_at: '2026-10-29T10:00:00',
    },
  ],
  ungrouped: [req(4, '2026-10-28T10:00:00')],
  total: 4,
}

describe('usePendingChanges（ADR 0005 M4）', () => {
  it('一次调用聚合端点（scope=open & group_by=row），不逐条 get 申请详情', async () => {
    const listCalls: URL[] = []
    const detailCalls: number[] = []
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/:tid/change-requests', ({ request }) => {
        listCalls.push(new URL(request.url))
        return HttpResponse.json(groupedPage)
      }),
      http.get('/api/v1/workspaces/:wid/tables/:tid/change-requests/:id', ({ params }) => {
        detailCalls.push(Number(params.id))
        return HttpResponse.json({})
      }),
    )

    const { result } = renderHook(() => usePendingChanges('10', '100'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeInstanceOf(Map))

    // 聚合端点恰好一次，且参数正确
    expect(listCalls).toHaveLength(1)
    expect(listCalls[0].searchParams.get('scope')).toBe('open')
    expect(listCalls[0].searchParams.get('group_by')).toBe('row')
    // 详情端点零请求（N+1 已消除）
    expect(detailCalls).toHaveLength(0)
  })

  it('Map 为 rowId → 组内最新申请，ungrouped（create-only）不进 Map', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/:tid/change-requests', () => HttpResponse.json(groupedPage)),
    )
    const { result } = renderHook(() => usePendingChanges('10', '100'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeInstanceOf(Map))

    const map = result.current.data!
    expect(map.size).toBe(2)
    expect(map.get('1')?.id).toBe(2) // 行 1 组内最新（created_at 倒序取 [0]）
    expect(map.get('2')?.id).toBe(3)
    expect(map.has('4')).toBe(false) // ungrouped 无行归属，不参与行级标识
  })

  it('enabled=false 或 wid/tid 缺失时不发请求', async () => {
    const listFn = vi.fn()
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/:tid/change-requests', () => {
        listFn()
        return HttpResponse.json(groupedPage)
      }),
    )
    const { result } = renderHook(() => usePendingChanges('10', '100', false), { wrapper })
    expect(result.current.data).toBeUndefined()
    await new Promise(r => setTimeout(r, 50))
    expect(listFn).not.toHaveBeenCalled()

    const disabled = renderHook(() => usePendingChanges(undefined, undefined), { wrapper })
    await new Promise(r => setTimeout(r, 50))
    expect(disabled.result.current.data).toBeUndefined()
    expect(listFn).not.toHaveBeenCalled()
  })
})

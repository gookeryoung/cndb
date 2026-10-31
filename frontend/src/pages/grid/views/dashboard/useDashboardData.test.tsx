/** dashboard 服务端批量取数 hook 测试（ADR 0023 P2）.
 *
 * 覆盖：只请求落库的数据 widget / 小表禁用不发请求 / 响应拆分为 datasets、errors、meta /
 * loading 与 refetch。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { waitFor } from '@testing-library/react'
import { renderHookProviders } from '@/test/render-providers'
import type { View } from '@/api'
import { useDashboardData } from './useDashboardData'

const dashboardData = vi.hoisted(() => vi.fn())
vi.mock('@/api/views', () => ({ viewApi: { dashboardData } }))

function makeView(widgets: unknown[]): View {
  return {
    id: 7,
    name: '大表画布',
    view_type: 'dashboard',
    is_default: false,
    updated_at: '2026-10-31T00:00:00.000000Z',
    view_options: { schema_version: 1, widgets },
  } as unknown as View
}

const WIDGETS = [
  { id: 'chart-1', type: 'chart' },
  { id: 'kpi-1', type: 'kpi' },
  { id: 'table-1', type: 'table' },
  { id: 'note', type: 'text' },
  { id: 42, type: 'chart' },
  null,
]

const OK_RESPONSE = {
  items: [
    {
      widget_id: 'chart-1',
      dataset: { kind: 'category', categories: ['A'], series: [{ name: 's', data: [1] }] },
      meta: { scanned: 10, total: 12000, truncated: true, cached: false },
    },
    {
      widget_id: 'kpi-1',
      dataset: { kind: 'kpi', field: '销售额', agg: 'sum', value: 9 },
      meta: { scanned: 10, total: 12000, truncated: true, cached: true },
    },
    {
      widget_id: 'table-1',
      dataset: 'broken',
      meta: { scanned: 10, total: 12000, truncated: true, cached: false },
    },
  ],
  errors: [{ widget_id: 'chart-1', detail: '字段缺失' }],
}

beforeEach(() => {
  dashboardData.mockReset()
  dashboardData.mockResolvedValue({ items: [], errors: [] })
})

describe('useDashboardData', () => {
  it('小表禁用时不发请求', () => {
    const view = makeView(WIDGETS)
    const { result } = renderHookProviders(() =>
      useDashboardData({ wid: 1, tid: 2, view, enabled: false }))
    expect(dashboardData).not.toHaveBeenCalled()
    expect(result.current.datasets.size).toBe(0)
    expect(result.current.loading).toBe(false)
  })

  it('只提交落库的 chart / kpi / table widget', async () => {
    const view = makeView(WIDGETS)
    renderHookProviders(() => useDashboardData({ wid: 1, tid: 2, view, enabled: true }))
    await waitFor(() => expect(dashboardData).toHaveBeenCalled())
    expect(dashboardData.mock.calls[0][3]).toEqual({ widget_ids: ['chart-1', 'kpi-1', 'table-1'] })
  })

  it('响应拆分为 datasets / errors / meta，非法 dataset 记错误', async () => {
    dashboardData.mockResolvedValue(OK_RESPONSE)
    const view = makeView(WIDGETS)
    const { result } = renderHookProviders(() =>
      useDashboardData({ wid: 1, tid: 2, view, enabled: true }))

    await waitFor(() => expect(result.current.datasets.size).toBe(2))
    expect(result.current.datasets.get('chart-1')).toMatchObject({ kind: 'category' })
    expect(result.current.datasets.get('kpi-1')).toMatchObject({ kind: 'kpi', value: 9 })
    expect(result.current.datasets.get('kpi-1')?.meta?.cached).toBe(true)
    // 非法 dataset 只记错误，不进入 datasets / meta
    expect(result.current.datasets.has('table-1')).toBe(false)
    expect(result.current.errors.get('table-1')).toBe('数据格式异常')
    // 接口 errors 覆盖同 id 的其它失败文案
    expect(result.current.errors.get('chart-1')).toBe('字段缺失')
    expect(result.current.loading).toBe(false)
  })

  it('接口 errors 缺 detail 时给默认文案', async () => {
    dashboardData.mockResolvedValue({ items: [], errors: [{ widget_id: 'kpi-1', detail: '' }] })
    const view = makeView(WIDGETS)
    const { result } = renderHookProviders(() =>
      useDashboardData({ wid: 1, tid: 2, view, enabled: true }))
    await waitFor(() => expect(result.current.errors.size).toBe(1))
    expect(result.current.errors.get('kpi-1')).toBe('取数失败')
  })

  it('refetch 重新请求', async () => {
    dashboardData.mockResolvedValue({ items: [], errors: [] })
    const view = makeView(WIDGETS)
    const { result } = renderHookProviders(() =>
      useDashboardData({ wid: 1, tid: 2, view, enabled: true }))
    await waitFor(() => expect(dashboardData).toHaveBeenCalledTimes(1))
    result.current.refetch()
    await waitFor(() => expect(dashboardData).toHaveBeenCalledTimes(2))
  })
})

/** GridPage 行深链接测试 —— 回归 "工作区搜索命中行后跳到表页但未定位到对应行" 的问题.
 *
 * 搜索命中行 → GlobalSearch 以 `?row=<id>` 跳转 → GridPage 读参数：
 * 行在当前页则滚动定位，不在当前页则拉取单行；两者都打开行详情抽屉并清掉参数。
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { preloadGridViews } from '@/test/preloadGridViews'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'

beforeAll(async () => {
  await preloadGridViews()
})

const MOCK_FIELDS = [
  { id: 1, name: '姓名', field_type: 'text', order: 1, required: true },
  { id: 2, name: '年龄', field_type: 'number', order: 2, required: false },
] as any

const MOCK_ROWS = Array.from({ length: 5 }, (_, i) => ({
  id: i + 1,
  姓名: `name-${i}`,
  年龄: 20 + i,
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
}))

vi.mock('@/api/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hooks')>()
  return {
    ...actual,
    useTable: () => ({
      data: {
        id: 1,
        workspace_id: 1,
        name: '测试表',
        fields: MOCK_FIELDS,
        current_user_actions: ['edit_records', 'edit_schema'],
      } as any,
      isLoading: false,
    }),
    useTableViews: () => ({ data: [] }),
    useTableRecords: () => ({
      data: { items: MOCK_ROWS, total: 500, offset: 0, limit: 5 },
      isFetching: false,
    }),
    useUpdateRowOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
    useDeleteRowsOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
  }
})

vi.mock('@/api', () => ({
  useLlmConfigured: () => true,
  tableApi: { get: vi.fn(), references: vi.fn() },
  recordApi: {
    list: vi.fn(),
    get: vi.fn().mockResolvedValue({
      id: 999,
      姓名: 'off-page-row',
      年龄: 1,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    }),
    create: vi.fn().mockResolvedValue({ id: 999 }),
    update: vi.fn(),
    bulkDelete: vi.fn(),
    bulkCreate: vi.fn().mockResolvedValue({ ids: [] }),
  },
  viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
  auditApi: { list: vi.fn().mockResolvedValue([]) },
  preferencesApi: {
    get: vi.fn().mockResolvedValue({ active_views: {}, workspace_order: [], favorite_view_ids: [] }),
  },
}))

import { recordApi } from '@/api'

beforeEach(() => {
  useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 5, newRowPosition: 'page' })
})

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname + loc.search}</div>
}

function renderGridAt(route: string) {
  renderProviders(
    <>
      <Routes>
        <Route path="w/:wid/tables/:tid" element={<GridPage />} />
      </Routes>
      <LocationProbe />
    </>,
    {
      route,
      initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' },
    },
  )
}

describe('GridPage 工作区搜索行定位（?row=<id> 深链接）', () => {
  it('行在当前页：打开行详情抽屉并清掉 ?row 参数', async () => {
    renderGridAt('/w/1/tables/1?row=2')
    expect(await screen.findByText('行详情 #2')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('loc').textContent).toBe('/w/1/tables/1')
    })
  })

  it('行不在当前页（分页外）：拉取单行打开详情并清参', async () => {
    renderGridAt('/w/1/tables/1?row=999')
    expect(await screen.findByText('行详情 #999')).toBeInTheDocument()
    expect(recordApi.get).toHaveBeenCalledWith('1', '1', '999')
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/w/1/tables/1'))
  })
})

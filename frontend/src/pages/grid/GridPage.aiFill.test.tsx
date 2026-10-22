/** GridPage 列头 AI 填充接线测试（ADR 0020 P2）.
 *
 * 断言：列头入口点击 → 懒加载 AiFillFieldDrawer → 按当前页可读行调用 fill_field
 * 建议端点；整条链路不写库（应用动作由 Drawer 单测覆盖）。
 */

import { describe, expect, it, vi, beforeEach, beforeAll } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { preloadGridViews } from '@/test/preloadGridViews'
import { server } from '@/test/msw'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'

beforeAll(async () => {
  await preloadGridViews()
})

const FIELDS = [
  { id: 1, name: '姓名', field_type: 'text', order: 1 },
  { id: 2, name: '摘要', field_type: 'longtext', order: 2 },
  { id: 9, name: '隐藏列', field_type: 'text', order: 3, hidden: true },
] as any

const ROWS = [
  { id: 1, 姓名: '张三', 摘要: '' },
  { id: 2, 姓名: '李四', 摘要: '' },
] as any

vi.mock('@/api/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hooks')>()
  return {
    ...actual,
    useTable: () => ({
      data: {
        id: 1, workspace_id: 1, name: '测试表', fields: FIELDS,
        current_user_actions: ['edit_records', 'edit_schema'],
      },
      isLoading: false,
    }),
    useTableViews: () => ({
      data: [{
        id: 7, name: '全部', view_type: 'grid', is_default: true,
        filters: [], sortings: [], filter_type: 'AND', view_options: {}, order: 0,
      }],
    }),
    useTableRecords: () => ({ data: { items: ROWS, total: 2, offset: 0, limit: 20 }, isFetching: false }),
    useUpdateRowOptimistic: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useDeleteRowsOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
  }
})

vi.mock('@/api', () => ({
  tableApi: { get: vi.fn(), references: vi.fn(), aiFillField: vi.fn() },
  recordApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), bulkDelete: vi.fn(), bulkCreate: vi.fn() },
  viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
  auditApi: { list: vi.fn() },
  preferencesApi: {
    get: vi.fn().mockResolvedValue({ active_views: {}, workspace_order: [], favorite_view_ids: [] }),
  },
  changeRequestsApi: { listGrouped: vi.fn().mockResolvedValue({ groups: [], ungrouped: [], total: 0 }) },
  isChangeRequestResponse: () => false,
}))

beforeEach(() => {
  useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 20 })
})

function renderGrid() {
  return renderProviders(
    <Routes>
      <Route path="w/:wid/tables/:tid" element={<GridPage />} />
    </Routes>,
    {
      route: '/w/1/tables/1',
      initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' },
    },
  )
}

describe('GridPage 列头 AI 填充接线', () => {
  it('点击列头入口：懒加载抽屉并对当前页行发起 fill_field 建议请求', async () => {
    const bodies: any[] = []
    server.use(
      http.post('/api/v1/workspaces/:wid/tables/:tid/ai/actions/fill_field', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({
          action: 'table.fill_field',
          run_id: 12,
          model: 'mock-model',
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
          result: { values: [{ row_id: 1, value: '模型摘要' }] },
          skipped_row_ids: [],
          row_count: 2,
        })
      }),
    )

    renderGrid()

    // 只在可见字段出现入口；hidden 字段不出列
    const entry = await screen.findByTestId('header-ai-fill-2', {}, { timeout: 3000 })
    expect(screen.queryByTestId('header-ai-fill-9')).toBeNull()

    fireEvent.click(entry)

    expect(await screen.findByTestId('ai-fill-field-drawer', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(await screen.findByTestId('ai-fill-value-1', {}, { timeout: 3000 })).toHaveTextContent('模型摘要')
    expect(bodies).toHaveLength(1)
    expect(bodies[0].field_name).toBe('摘要')
    expect(bodies[0].row_ids).toEqual([1, 2])
  })
})

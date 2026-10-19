/**
 * GridPage 移动表（跨工作区）流程测试.
 *
 * 覆盖：
 *  - 打开「更多 → 移动到其他工作区」弹窗；
 *  - 未选择目标工作区时点击「移动」→ 给出错误提示且不发起移动请求；
 *  - 选择目标工作区后点击「移动」→ 调用移动接口并携带目标工作区 id.
 */

import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { preloadGridViews } from '@/test/preloadGridViews'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'
import { tableApi } from '@/api'

beforeAll(async () => {
  await preloadGridViews()
})

const FIELDS = [{ id: 1, name: '姓名', field_type: 'text', order: 1, required: true }] as any
const VIEWS = [
  { id: 10, name: '全部数据', view_type: 'grid', is_default: true, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
] as any

vi.mock('@/api/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hooks')>()
  return {
    ...actual,
    useTable: () => ({
      data: {
        id: 1, workspace_id: 1, name: '测试表', fields: FIELDS,
        current_user_actions: ['edit_records', 'edit_schema'],
      } as any,
      isLoading: false,
    }),
    useTableViews: () => ({ data: VIEWS }),
    useTableRecords: () => ({ data: { items: [], total: 0, offset: 0, limit: 20 } }),
    useUpdateRowOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
    useDeleteRowsOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
  }
})

vi.mock('@/api', () => ({
  tableApi: { get: vi.fn(), references: vi.fn(), move: vi.fn().mockResolvedValue({ id: 1, workspace_id: 10 }) },
  recordApi: {
    list: vi.fn(),
    create: vi.fn().mockResolvedValue({ id: 999 }),
    update: vi.fn(),
    bulkDelete: vi.fn(),
    bulkCreate: vi.fn().mockResolvedValue({ ids: [] }),
  },
  viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
  auditApi: { list: vi.fn() },
  // 移动表的候选来源：唯一工作区 id=10 与当前工作区（wid=1）不同，可作为目标
  workspaceApi: { list: vi.fn().mockResolvedValue([{ id: 10, name: '测试工作区' }]) },
}))

beforeEach(() => {
  useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 20 })
  vi.clearAllMocks()
})

function renderGrid() {
  renderProviders(
    <Routes>
      <Route path="w/:wid/tables/:tid" element={<GridPage />} />
    </Routes>,
    { route: '/w/1/tables/1', initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' } },
  )
}

/** 打开「更多」菜单 → 点击「移动到其他工作区」→ 等待弹窗与选择器就绪 */
async function openMoveModal() {
  fireEvent.click(await screen.findByTestId('grid-more-menu'))
  fireEvent.click(await screen.findByText('移动到其他工作区'))
  await screen.findByText('选择目标工作区')
}

/** 点击弹窗底部的主按钮（antd Modal 的 okText="移动"） */
function clickModalOk() {
  fireEvent.click(document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement)
}

describe('GridPage 移动表到其他工作区', () => {
  it('未选择目标工作区时点击「移动」给出错误提示且不调用接口', async () => {
    renderGrid()
    await openMoveModal()

    clickModalOk()

    expect(await screen.findByText('请先选择目标工作区')).toBeInTheDocument()
    expect(tableApi.move).not.toHaveBeenCalled()
  })

  it('选择目标工作区后点击「移动」调用移动接口并携带目标工作区 id', async () => {
    renderGrid()
    await openMoveModal()

    fireEvent.mouseDown(screen.getByText('选择目标工作区'))
    fireEvent.click(await screen.findByText('测试工作区', { selector: '.ant-select-item-option-content' }))
    clickModalOk()

    await waitFor(() => expect(tableApi.move).toHaveBeenCalledWith('1', '1', 10))
  })
})

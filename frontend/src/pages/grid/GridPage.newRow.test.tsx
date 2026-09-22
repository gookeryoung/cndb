/** GridPage 新增行可见性测试 —— 回归 "满员页追加 newRow 被 AntD 分页切片切掉" 的 bug.
 *
 * 根因：AntD Table 的 pageData 在 dataSource.length > pageSize 时执行
 * `mergedData.slice((current-1)*pageSize, current*pageSize)`，把追加在末尾的 newRow
 * （index === pageSize）切掉。修复方案：Table pagination={false}，改用独立 Pagination
 * 组件，Table 完整渲染 dataSource，newRow 始终可见。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'

// ── mock 数据 ──────────────────────────────────────────────────────────────

const MOCK_FIELDS = [
  { id: 1, name: '姓名', field_type: 'text', order: 1, required: true },
  { id: 2, name: '年龄', field_type: 'number', order: 2, required: false },
] as any

/** 生成 N 条 mock 行 */
function makeRows(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    姓名: `name-${i}`,
    年龄: 20 + i,
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
  }))
}

// ── mock hooks（部分 mock：保留原始实现，覆盖关键 hooks）──────────────────

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
      data: { items: makeRows(5), total: 500, offset: 0, limit: 5 },
    }),
    useUpdateRowOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
    useDeleteRowsOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
  }
})

// mock recordApi / tableApi 等，避免点击保存时打到真实网络
vi.mock('@/api', () => ({
  tableApi: { get: vi.fn(), references: vi.fn() },
  recordApi: {
    list: vi.fn(),
    create: vi.fn().mockResolvedValue({ id: 999 }),
    update: vi.fn(),
    bulkDelete: vi.fn(),
    bulkCreate: vi.fn().mockResolvedValue({ ids: [] }),
  },
  viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
  auditApi: { list: vi.fn() },
}))

beforeEach(() => {
  // 重置设置 store：小页容量 5，mock 返回 5 行（满员页），验证 newRow 追加后不被切片
  useTableSettingsStore.setState({
    density: 'comfortable',
    defaultPageSize: 5,
    bordered: false,
    showHeader: true,
    striped: false,
    newRowPosition: 'page',
  })
})

/** 渲染 GridPage 并等待表格就绪 */
function renderGrid(position: 'top' | 'tail' | 'page') {
  useTableSettingsStore.getState().updateSettings({ newRowPosition: position })
  renderProviders(
    <Routes>
      <Route path="w/:wid/tables/:tid" element={<GridPage />} />
    </Routes>,
    {
      route: '/w/1/tables/1',
      initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' },
    },
  )
}

describe('GridPage 新增行可见性（回归：满员页 newRow 被切掉）', () => {
  it('页面尾部：满员页（50条）点击新增行后，newRow 直接出现在当前页底部并可见', () => {
    renderGrid('page')
    const addBtn = screen.getByTestId('add-row-btn')
    fireEvent.click(addBtn)

    // newRow 必须出现在 DOM 中（data-row-key="__new__"）
    const newRow = document.querySelector('[data-row-key="__new__"]')
    expect(newRow).toBeInTheDocument()
    // 且该行含有可编辑输入框（行内编辑已激活）
    expect(newRow?.querySelector('input')).toBeInTheDocument()
  })

  it('表格尾部：点击新增行后，自动跳转到最后一页且 newRow 可见', () => {
    renderGrid('tail')
    const addBtn = screen.getByTestId('add-row-btn')
    fireEvent.click(addBtn)

    const newRow = document.querySelector('[data-row-key="__new__"]')
    expect(newRow).toBeInTheDocument()
    expect(newRow?.querySelector('input')).toBeInTheDocument()
  })

  it('表格顶部：点击新增行后，newRow 出现在表格顶部（第一条）且可见', () => {
    renderGrid('top')
    const addBtn = screen.getByTestId('add-row-btn')
    fireEvent.click(addBtn)

    const newRow = document.querySelector('[data-row-key="__new__"]')
    expect(newRow).toBeInTheDocument()
    // 顶部模式下 newRow 应是第一个 data-row-key 元素
    const allRows = document.querySelectorAll('[data-row-key]')
    expect(allRows[0]?.getAttribute('data-row-key')).toBe('__new__')
  })

  it('取消新增后 newRow 从 DOM 中移除', () => {
    renderGrid('page')
    fireEvent.click(screen.getByTestId('add-row-btn'))
    expect(document.querySelector('[data-row-key="__new__"]')).toBeInTheDocument()

    // 点击取消按钮
    const cancelBtn = screen.getByTestId('row-cancel-btn')
    fireEvent.click(cancelBtn)

    expect(document.querySelector('[data-row-key="__new__"]')).not.toBeInTheDocument()
  })

  it('点击新增行后自动聚焦新行第一个可编辑输入框（jsdom 下只覆盖聚焦行为，滚动机制由 useNewRowAutoScroll 单测锁定）', async () => {
    renderGrid('page')
    fireEvent.click(screen.getByTestId('add-row-btn'))

    await waitFor(() => {
      const row = document.querySelector('[data-row-key="__new__"]')
      expect(row).toBeInTheDocument()
      // 聚焦落在新行内部的可编辑输入框上
      expect(row?.contains(document.activeElement)).toBe(true)
      expect(document.activeElement?.tagName).toBe('INPUT')
    })
  })
})

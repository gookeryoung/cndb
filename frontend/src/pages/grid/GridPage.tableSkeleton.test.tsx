/**
 * TableSkeleton 列数对齐 table.fields 回归.
 *
 * 语义：骨架屏列数取「最近一次已加载表的可见字段数」（hidden 字段不计入）；
 *      切表元数据未到（isLoading）时按该参考渲染，冷启动无参考退化为 6。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore } from '@/store'
import GridPage from './GridPage'

/** hoisted 持有可变 useTable 返回值，用例内按场景改写后 rerender（避免 TDZ） */
const tableRef = vi.hoisted(() => ({
  current: { isLoading: true, data: undefined as any },
}))

vi.mock('@/api/hooks', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/api/hooks')>()
    return {
        ...actual,
        useTable: () => tableRef.current,
        useTableViews: () => ({ data: [] }),
        useTableRecords: () => ({ data: { items: [], total: 0, offset: 0, limit: 20 }, isFetching: false }),
        useUpdateRowOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
        useDeleteRowsOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
    }
})

vi.mock('@/api', () => ({
    tableApi: { get: vi.fn(), references: vi.fn() },
    recordApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), bulkDelete: vi.fn(), bulkCreate: vi.fn().mockResolvedValue({ ids: [] }) },
    viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
    auditApi: { list: vi.fn() },
}))

beforeEach(() => {
    useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 20 })
})

/** 4 个可见字段 + 1 个 hidden 字段（hidden 不计入骨架列数） */
const FIELDS = [
    { id: 1, name: '甲', field_type: 'text', order: 1 },
    { id: 2, name: '乙', field_type: 'text', order: 2 },
    { id: 3, name: '丙', field_type: 'text', order: 3 },
    { id: 4, name: '丁', field_type: 'text', order: 4 },
    { id: 9, name: '隐藏列', field_type: 'text', order: 5, hidden: true },
] as any

const ui = (
    <Routes>
        <Route path="w/:wid/tables/:tid" element={<GridPage />} />
    </Routes>
)

function renderGrid() {
    return renderProviders(ui, {
        route: '/w/1/tables/1',
        initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' },
    })
}

/** 读取骨架屏表头占位条数量（即骨架列数） */
function skeletonColCount(): number {
    return document.querySelector('[data-testid="table-skeleton"] > div:first-child')?.children.length ?? -1
}

describe('TableSkeleton 列数对齐 table.fields', () => {
    it('冷启动元数据未到时退化为 6 列', () => {
        tableRef.current = { isLoading: true, data: undefined }
        renderGrid()
        expect(skeletonColCount()).toBe(6)
    })

    it('切表元数据未到时按上一张表可见字段数渲染，hidden 字段不计入', async () => {
        // 1) 冷启动骨架（无参考，退化 6 列）
        tableRef.current = { isLoading: true, data: undefined }
        const { rerender } = renderGrid()
        expect(skeletonColCount()).toBe(6)

        // 2) 表元数据到达（4 可见 + 1 hidden），骨架消失
        tableRef.current = {
            isLoading: false,
            data: { id: 1, workspace_id: 1, name: '表A', fields: FIELDS, current_user_actions: ['edit_records'] },
        }
        rerender(ui)
        await waitFor(() => expect(document.querySelector('[data-testid="table-skeleton"]')).toBeNull())

        // 3) 模拟切表：元数据未到（isLoading），骨架按上次可见字段数 4 渲染
        tableRef.current = { isLoading: true, data: undefined }
        rerender(ui)
        expect(skeletonColCount()).toBe(4)
    })
})

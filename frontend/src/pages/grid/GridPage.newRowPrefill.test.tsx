/** GridPage 新增行预填测试 —— default_value 字段与 auto_fill 日期字段在新增行激活时按规则预填.
 *
 * 验收（表设置字段增强需求 3）：
 *  1. text 字段配置 default_value='待办' → 新增行草稿预填「待办」
 *  2. date 字段配置 auto_fill=on_create → 新增行草稿预填当天日期
 *  3. 未配置任何默认的字段保持空白
 *  4. text 字段启用自动编号（config.default_mode=auto_increment）→ 不预填（编号由后端建行时生成）
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, fireEvent, within } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import dayjs from 'dayjs'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'

// ── mock 数据 ──────────────────────────────────────────────────────────────

const MOCK_FIELDS = [
    { id: 1, name: '姓名', field_type: 'text', order: 1, required: true },
    { id: 2, name: '状态', field_type: 'text', order: 2, default_value: '待办' },
    { id: 3, name: '创建日期', field_type: 'date', order: 3, config: { auto_fill: 'on_create' } },
    { id: 4, name: '编号', field_type: 'text', order: 4, config: { default_mode: 'auto_increment', increment_prefix: 'PRJ-' } },
] as any

/** 生成 N 条 mock 行 */
function makeRows(n: number) {
    return Array.from({ length: n }, (_, i) => ({
        id: i + 1,
        姓名: `name-${i}`,
        created_at: '2026-01-01',
        updated_at: '2026-01-01',
    }))
}

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
    useTableSettingsStore.setState({
        density: 'comfortable',
        defaultPageSize: 5,
        bordered: false,
        showHeader: true,
        striped: false,
        newRowPosition: 'page',
        // 本测试断言预填值进入可编辑输入框，需显式关闭「自动预填锁定」（默认开启，开启时预填字段渲染为只读文本）
        autoFillLocked: false,
    })
})

describe('GridPage 新增行预填（default_value / auto_fill）', () => {
    it('点击新增行后：default_value 字段预填「待办」，auto_fill date 字段预填今天，其余为空', () => {
        useTableSettingsStore.getState().updateSettings({ newRowPosition: 'page' })
        renderProviders(
            <Routes>
                <Route path="w/:wid/tables/:tid" element={<GridPage />} />
            </Routes>,
            {
                route: '/w/1/tables/1',
                initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' },
            },
        )
        fireEvent.click(screen.getByTestId('add-row-btn'))

        const newRow = document.querySelector('[data-row-key="__new__"]') as HTMLElement | null
        expect(newRow).toBeInTheDocument()

        // default_value 预填
        expect(within(newRow!).getByDisplayValue('待办')).toBeInTheDocument()
        // auto_fill=on_create 的 date 字段预填今天（DatePicker 输入框显示 YYYY-MM-DD）
        expect(within(newRow!).getByDisplayValue(dayjs().format('YYYY-MM-DD'))).toBeInTheDocument()
        // 未配置默认的「姓名」与自动编号「编号」保持空白（编号由后端建行时生成，不预填）
        const blanks = within(newRow!).getAllByDisplayValue('')
        expect(blanks.length).toBeGreaterThanOrEqual(2)
    })
})

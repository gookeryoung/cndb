/**
 * GridPage 落地视图选择优先级回归.
 *
 * 语义：进入数据表时以「默认视图」（is_default）为落地视图，
 *      只有 URL ?view= 深链可以覆盖它；跨会话的个人偏好、URL ?mode=、
 *      localStorage mode 均不得抢跑默认视图。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'

const FIELDS = [{ id: 1, name: '姓名', field_type: 'text', order: 1, required: true }] as any

/** 三个 grid 视图：默认视图刻意放在中间（index 1），验证落地不是「取第一个」 */
const VIEWS = [
    { id: 10, name: '视图A', view_type: 'grid', is_default: false, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
    { id: 11, name: '默认视图', view_type: 'grid', is_default: true, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
    { id: 12, name: '视图B', view_type: 'grid', is_default: false, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
] as any

/** 无默认视图的表（用于验证兜底到第一个视图） */
const VIEWS_NO_DEFAULT = [
    { id: 20, name: '首个视图', view_type: 'grid', is_default: false, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
    { id: 21, name: '次个视图', view_type: 'grid', is_default: false, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
] as any

/** hoisted 持有可变 views，供 mock 工厂在调用时读取（避免 TDZ） */
const viewsRef = vi.hoisted(() => ({ current: [] as any[] }))

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
        useTableViews: () => ({ data: viewsRef.current }),
        useTableRecords: () => ({ data: { items: [], total: 0, offset: 0, limit: 20 } }),
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
    viewsRef.current = VIEWS
    useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 20 })
    // 模拟「上次访问留下的 mode 记忆」，验证它不再抢跑默认视图
    localStorage.setItem('cndb_current_mode', 'grid')
})

/** 读取 Segmented 当前选中的视图名 */
function selectedViewName(): string {
    return (document.querySelector('.ant-segmented-item-selected')?.textContent ?? '').trim()
}

function renderGrid(route = '/w/1/tables/1') {
    renderProviders(
        <Routes>
            <Route path="w/:wid/tables/:tid" element={<GridPage />} />
        </Routes>,
        { route, initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' } },
    )
}

describe('GridPage 落地视图 — 默认视图优先', () => {
    it('无 URL 参数时落到默认视图，而非第一个视图', async () => {
        renderGrid()
        await waitFor(() => expect(selectedViewName()).toContain('默认视图'))
        expect(selectedViewName()).not.toContain('视图A')
    })

    it('URL ?view= 深链可覆盖默认视图', async () => {
        renderGrid('/w/1/tables/1?view=12')
        await waitFor(() => expect(selectedViewName()).toContain('视图B'))
    })

    it('默认视图存在时，URL ?mode= 与 localStorage mode 都不抢跑', async () => {
        renderGrid('/w/1/tables/1?mode=grid')
        await waitFor(() => expect(selectedViewName()).toContain('默认视图'))
    })

    it('表内无默认视图时兜底到第一个视图', async () => {
        viewsRef.current = VIEWS_NO_DEFAULT
        renderGrid()
        await waitFor(() => expect(selectedViewName()).toContain('首个视图'))
    })
})
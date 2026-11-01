/** GridPage 登录态只读展示态回归（ADR 0077 P1）.
 *
 * 语义：`?present=1` 只接受精确命中的 dashboard 视图；目标不可见 / 非画布时显示
 * 「链接无效或无权访问」，**不得回落到默认视图**；展示态隐藏页面工具栏、视图栏与聚合条。
 * 画布本体在此 mock 成桩组件，只验证页面接线（presenting / 行点击 / 退出 / 复制链接）。
 */

import { describe, expect, it, vi, beforeEach, beforeAll } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { preloadGridViews } from '@/test/preloadGridViews'
import { useGridViewStore } from '@/store/gridView'
import GridPage from './GridPage'

vi.mock('./views/dashboard/DashboardView', () => ({
  default: (props: {
    presenting?: boolean
    onRowClick?: unknown
    onExitPresent?: () => void
    onCopyShareLink?: () => void
  }) => (
    <div
      data-testid="dashboard-stub"
      data-presenting={String(!!props.presenting)}
      data-has-row-click={String(!!props.onRowClick)}
    >
      <button data-testid="stub-share" onClick={props.onCopyShareLink}>share</button>
      <button data-testid="stub-exit" onClick={props.onExitPresent}>exit</button>
    </div>
  ),
}))

beforeAll(async () => {
    await preloadGridViews()
})

const FIELDS = [{ id: 1, name: '姓名', field_type: 'text', order: 1, required: true }] as any

/** 默认视图刻意是 grid：展示态失配时若发生回落，就会渲染它而不是「链接无效」 */
const VIEWS = [
    { id: 10, name: '全部记录', view_type: 'grid', is_default: true, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
    { id: 11, name: '销售画布', view_type: 'dashboard', is_default: false, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
] as any

const viewsRef = vi.hoisted(() => ({ current: [] as any[] }))

vi.mock('@/api/hooks', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/api/hooks')>()
    return {
        ...actual,
        useTable: () => ({
            data: {
                id: 1, workspace_id: 1, name: '测试表', fields: FIELDS,
                current_user_actions: ['edit_records', 'edit_schema', 'edit_views'],
            } as any,
            isLoading: false,
        }),
        useTableViews: () => ({ data: viewsRef.current, isLoading: false }),
        useTableRecords: () => ({
            data: { items: [{ id: 1, 姓名: '张三' }], total: 1, offset: 0, limit: 20 },
            isFetching: false,
            isError: false,
            refetch: vi.fn(),
        }),
        useUpdateRowOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
        useDeleteRowsOptimistic: () => ({ mutate: vi.fn(), isPending: false }),
    }
})

vi.mock('@/api', () => ({
    useLlmConfigured: () => true,
    tableApi: { get: vi.fn(), references: vi.fn() },
    recordApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), bulkDelete: vi.fn(), bulkCreate: vi.fn().mockResolvedValue({ ids: [] }) },
    viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
    auditApi: { list: vi.fn() },
    preferencesApi: {
        get: vi.fn().mockResolvedValue({ active_views: {}, workspace_order: [], favorite_view_ids: [] }),
    },
}))

beforeEach(() => {
    viewsRef.current = VIEWS
    useGridViewStore.getState().reset()
})

function renderGrid(route: string) {
    return renderProviders(
        <Routes>
            <Route path="w/:wid/tables/:tid" element={<GridPage />} />
        </Routes>,
        { route, initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' } },
    )
}

describe('GridPage 只读展示态（present=1）', () => {
    it('命中 dashboard 视图：渲染画布展示态并隐藏页面工具栏 / 视图栏', async () => {
        renderGrid('/w/1/tables/1?view=11&mode=dashboard&present=1')

        const stub = await screen.findByTestId('dashboard-stub')
        expect(stub).toHaveAttribute('data-presenting', 'true')
        // 展示态禁用行详情
        expect(stub).toHaveAttribute('data-has-row-click', 'false')
        // 页面工具栏与视图栏隐藏
        expect(screen.queryByTestId('import-export-btn')).not.toBeInTheDocument()
        expect(screen.queryByTestId('view-more-desktop')).not.toBeInTheDocument()
    })

    it('目标视图不可见：显示「链接无效或无权访问」，不回落到默认 grid 视图', async () => {
        renderGrid('/w/1/tables/1?view=99&mode=dashboard&present=1')

        expect(await screen.findByTestId('dashboard-present-invalid')).toHaveTextContent('链接无效或无权访问')
        expect(screen.queryByTestId('dashboard-stub')).not.toBeInTheDocument()
    })

    it('目标不是画布视图：同样按链接失效处理', async () => {
        renderGrid('/w/1/tables/1?view=10&mode=dashboard&present=1')

        expect(await screen.findByTestId('dashboard-present-invalid')).toBeInTheDocument()
        expect(screen.queryByTestId('dashboard-stub')).not.toBeInTheDocument()
    })

    it('缺 view 参数：按链接失效处理，不回落默认视图', async () => {
        renderGrid('/w/1/tables/1?present=1')

        expect(await screen.findByTestId('dashboard-present-invalid')).toBeInTheDocument()
    })

    it('退出展示移除 present 参数并恢复页面工具栏', async () => {
        renderGrid('/w/1/tables/1?view=11&mode=dashboard&present=1')

        fireEvent.click(await screen.findByTestId('stub-exit'))

        await waitFor(() => expect(screen.getByTestId('dashboard-stub')).toHaveAttribute('data-presenting', 'false'))
        // 恢复常规页面：工具栏与视图栏重新出现
        expect(await screen.findByTestId('view-more-desktop')).toBeInTheDocument()
        expect(screen.getByTestId('import-export-btn')).toBeInTheDocument()
    })

    it('普通模式（无 present）不进入展示态，行点击仍接到详情', async () => {
        renderGrid('/w/1/tables/1?view=11&mode=dashboard')

        const stub = await screen.findByTestId('dashboard-stub')
        expect(stub).toHaveAttribute('data-presenting', 'false')
        expect(stub).toHaveAttribute('data-has-row-click', 'true')
        expect(screen.getByTestId('view-more-desktop')).toBeInTheDocument()
    })
})

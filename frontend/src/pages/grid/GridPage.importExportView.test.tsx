/**
 * GridPage 导出视图接线回归.
 *
 * 语义：打开「更新/导出」对话框时，必须把当前激活视图的 viewId/viewName
 *      传入对话框，使导出 Tab 默认「按当前视图筛选导出」；
 *      无激活视图时 viewId 为 null，导出全表数据.
 */

import { describe, expect, it, vi, beforeEach, beforeAll } from 'vitest'
import { waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { preloadGridViews } from '@/test/preloadGridViews'
import { useTableSettingsStore } from '@/store/tableSettings'
import GridPage from './GridPage'

beforeAll(async () => {
    await preloadGridViews()
})

const FIELDS = [{ id: 1, name: '姓名', field_type: 'text', order: 1, required: true }] as any

const VIEWS = [
    { id: 10, name: '视图A', view_type: 'grid', is_default: false, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
    { id: 11, name: '默认视图', view_type: 'grid', is_default: true, filters: [], sortings: [], filter_type: 'AND', field_order: [], view_options: {} },
] as any

/** hoisted 持有可变 views，供 mock 工厂在调用时读取（避免 TDZ） */
const viewsRef = vi.hoisted(() => ({ current: [] as any[] }))
/** 捕获 ImportExportDialog 收到的 props */
const dialogProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }))

vi.mock('@/pages/import-export/ImportExportDialog', () => ({
    default: (props: Record<string, unknown>) => {
        dialogProps.current = props
        return <div data-testid="ie-dialog-stub" data-view-id={props.viewId == null ? '' : String(props.viewId)} data-view-name={(props.viewName as string) ?? ''} />
    },
}))

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
    exportApi: { download: vi.fn() },
}))

beforeEach(() => {
    viewsRef.current = VIEWS
    dialogProps.current = null
    useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 20 })
    localStorage.setItem('cndb_current_mode', 'grid')
})

function renderGrid(route = '/w/1/tables/1') {
    renderProviders(
        <Routes>
            <Route path="w/:wid/tables/:tid" element={<GridPage />} />
        </Routes>,
        { route, initialAuth: { user: { id: 1, username: 'admin', role: 'admin' } as any, token: 'tok' } },
    )
}

async function openImportExportDialog() {
    fireEvent.click(await waitFor(() => {
        const btn = document.querySelector('[data-testid="import-export-btn"]') as HTMLButtonElement
        if (!btn) throw new Error('更新/导出按钮未渲染')
        return btn
    }))
    return waitFor(() => {
        const stub = document.querySelector('[data-testid="ie-dialog-stub"]')
        if (!stub) throw new Error('对话框未渲染')
        return stub as HTMLElement
    })
}

describe('GridPage 导出视图接线 — 对话框收到激活视图', () => {
    it('有激活视图时传入 viewId/viewName，导出默认按当前视图', async () => {
        renderGrid()
        const stub = await openImportExportDialog()
        expect(stub.getAttribute('data-view-id')).toBe('11')
        expect(stub.getAttribute('data-view-name')).toBe('默认视图')
    })

    it('无激活视图时 viewId 为 null，导出全表', async () => {
        viewsRef.current = []
        renderGrid()
        const stub = await openImportExportDialog()
        expect(stub.getAttribute('data-view-id')).toBe('')
    })

    it('传入 getPdfTarget，调用后返回主内容区元素（PDF 视觉快照目标）', async () => {
        renderGrid()
        await openImportExportDialog()
        const getPdfTarget = dialogProps.current?.getPdfTarget as (() => Promise<HTMLElement | null>) | undefined
        expect(typeof getPdfTarget).toBe('function')
        const el = await getPdfTarget?.()
        expect(el).toBeInstanceOf(HTMLElement)
        // releasePdfTarget 接线：导出结束后退出导出模式
        const releasePdfTarget = dialogProps.current?.releasePdfTarget
        expect(typeof releasePdfTarget).toBe('function')
    })
})

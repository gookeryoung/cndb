/**
 * GridPage 更新 / 导出对话框接线回归.
 *
 * 语义：工具栏「更新」与「导出」打开**两个独立对话框**（不再共用一个 3 Tab 弹窗）：
 *      - 更新 → UpdateDialog，只承载导入 / API 抓取；
 *      - 导出 → ExportDialog，接收当前激活视图的 viewId/viewName（按视图筛选导出）、
 *        getPdfTarget / releasePdfTarget（PDF 视觉快照与导出模式复位）。
 *      无激活视图时 viewId 为 null，导出全表数据.
 */

import { describe, expect, it, vi, beforeEach, beforeAll } from 'vitest'
import { waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { preloadGridViews } from '@/test/preloadGridViews'
import { useTableSettingsStore } from '@/store/tableSettings'
import { useGridViewStore } from '@/store/gridView'
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
/** 捕获 ExportDialog 收到的 props（视图接线 / PDF 目标） */
const exportDialogProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }))

vi.mock('@/pages/import-export/UpdateDialog', () => ({
    default: () => <div data-testid="update-dialog-stub" />,
}))

vi.mock('@/pages/import-export/ExportDialog', () => ({
    default: (props: Record<string, unknown>) => {
        exportDialogProps.current = props
        return (
            <div data-testid="export-dialog-stub"
                data-view-id={props.viewId == null ? '' : String(props.viewId)}
                data-view-name={(props.viewName as string) ?? ''} />
        )
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
    useLlmConfigured: () => true,
    tableApi: { get: vi.fn(), references: vi.fn() },
    recordApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), bulkDelete: vi.fn(), bulkCreate: vi.fn().mockResolvedValue({ ids: [] }) },
    viewApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() },
    auditApi: { list: vi.fn() },
    preferencesApi: {
        get: vi.fn().mockResolvedValue({ active_views: {}, workspace_order: [], favorite_view_ids: [] }),
    },
    exportApi: { download: vi.fn() },
}))

beforeEach(() => {
    viewsRef.current = VIEWS
    exportDialogProps.current = null
    useTableSettingsStore.setState({ density: 'comfortable', defaultPageSize: 20 })
    // GridPage 不再在每次挂载时清空视图状态（同表重挂载保留上轮视图，ADR 0116 C8），
    // 用例间必须显式复位，否则上一例的 activeViewId 会被下一例读到
    useGridViewStore.getState().reset()
    sessionStorage.clear()
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

async function clickToolbar(testId: string, label: string) {
    fireEvent.click(await waitFor(() => {
        const btn = document.querySelector(`[data-testid="${testId}"]`) as HTMLButtonElement
        if (!btn) throw new Error(`${label}按钮未渲染`)
        return btn
    }))
}

const openExportDialog = () => clickToolbar('export-btn', '导出')
const openUpdateDialog = () => clickToolbar('import-export-btn', '更新')

describe('GridPage 更新 / 导出对话框接线', () => {
    it('「导出」入口只打开导出对话框，不打开更新对话框', async () => {
        renderGrid()
        await openExportDialog()
        await waitFor(() => {
            expect(document.querySelector('[data-testid="export-dialog-stub"]')).not.toBeNull()
        })
        expect(document.querySelector('[data-testid="update-dialog-stub"]')).toBeNull()
    })

    it('「更新」入口只打开更新对话框，不打开导出对话框', async () => {
        renderGrid()
        await openUpdateDialog()
        await waitFor(() => {
            expect(document.querySelector('[data-testid="update-dialog-stub"]')).not.toBeNull()
        })
        expect(document.querySelector('[data-testid="export-dialog-stub"]')).toBeNull()
    })

    it('有激活视图时导出对话框收到 viewId/viewName，默认按当前视图', async () => {
        renderGrid()
        await openExportDialog()
        const stub = await waitFor(() => {
            const el = document.querySelector('[data-testid="export-dialog-stub"]')
            if (!el) throw new Error('导出对话框未渲染')
            return el as HTMLElement
        })
        expect(stub.getAttribute('data-view-id')).toBe('11')
        expect(stub.getAttribute('data-view-name')).toBe('默认视图')
    })

    it('无激活视图时 viewId 为 null，导出全表', async () => {
        viewsRef.current = []
        renderGrid()
        await openExportDialog()
        const stub = await waitFor(() => {
            const el = document.querySelector('[data-testid="export-dialog-stub"]')
            if (!el) throw new Error('导出对话框未渲染')
            return el as HTMLElement
        })
        expect(stub.getAttribute('data-view-id')).toBe('')
    })

    it('导出对话框收到 getPdfTarget / releasePdfTarget 接线（PDF 视觉快照）', async () => {
        renderGrid()
        await openExportDialog()
        await waitFor(() => {
            expect(exportDialogProps.current).not.toBeNull()
        })
        const getPdfTarget = exportDialogProps.current?.getPdfTarget as (() => Promise<HTMLElement | null>) | undefined
        expect(typeof getPdfTarget).toBe('function')
        const el = await getPdfTarget?.()
        expect(el).toBeInstanceOf(HTMLElement)
        // releasePdfTarget 接线：导出结束后退出导出模式
        const releasePdfTarget = exportDialogProps.current?.releasePdfTarget
        expect(typeof releasePdfTarget).toBe('function')
    })
})

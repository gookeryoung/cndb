/**
 * 文档模块布局测试 —— 桌面端左树右内容双栏；移动端树收入抽屉（FAB 触达）.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import DocumentsLayout from './DocumentsLayout'
import { renderProviders } from '@/test/render-providers'
import { mockUser } from '@/test/msw'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端，移动端用例在 beforeEach 中切换
let responsiveState: ResponsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
    const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
    return { ...actual, useResponsive: () => responsiveState }
})

/** 右栏路由桩：模拟总览/编辑器内容 */
function ContentStub() {
    return <div data-testid="doc-content-stub">内容区</div>
}

function renderLayout(route = '/w/10/documents') {
    return renderProviders(
        <Routes>
            <Route path="/w/:wid/documents" element={<DocumentsLayout />}>
                <Route index element={<ContentStub />} />
            </Route>
        </Routes>,
        { route, initialAuth: { user: mockUser, token: 'fake-token' } },
    )
}

describe('DocumentsLayout 桌面端', () => {
    it('左树右内容双栏：树与右栏内容同时渲染', async () => {
        renderLayout()

        expect(screen.getByTestId('doc-tree-aside')).toBeVisible()
        expect(screen.getByTestId('doc-content-stub')).toBeVisible()
        // 常驻树挂载并请求 tree 数据（msw 返回根文件夹）
        expect(await screen.findByTestId('doc-tree-folder-1')).toBeVisible()
        // 移动端 FAB 不渲染
        expect(screen.queryByTestId('doc-tree-fab')).toBeNull()
    })
})

describe('DocumentsLayout 移动端', () => {
    beforeEach(() => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
    })

    it('无常驻左栏，FAB 打开抽屉树，选中文档后抽屉收起', async () => {
        renderLayout()

        // 移动端不渲染常驻左栏，仅内容区 + FAB
        expect(screen.queryByTestId('doc-tree-aside')).toBeNull()
        expect(screen.getByTestId('doc-content-stub')).toBeVisible()
        expect(screen.getByTestId('doc-tree-fab')).toBeVisible()

        // FAB 打开抽屉 → 树渲染
        fireEvent.click(screen.getByTestId('doc-tree-fab'))
        await waitFor(() => {
            expect(document.querySelector('.ant-drawer-open')).not.toBeNull()
        })
        expect(await screen.findByTestId('doc-tree-folder-1')).toBeVisible()

        // 点击文档节点后抽屉自动收起（onNavigate 回调闭环）
        fireEvent.click(screen.getByTestId('doc-tree-folder-1'))
        await waitFor(() => {
            expect(screen.getByTestId('doc-tree-doc-2')).toBeVisible()
        })
        fireEvent.click(screen.getByTestId('doc-tree-doc-2'))
        await waitFor(() => {
            expect(document.querySelector('.ant-drawer-open')).toBeNull()
        })
    })
})

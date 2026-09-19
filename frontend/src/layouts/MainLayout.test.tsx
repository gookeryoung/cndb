/**
 * MainLayout 顶部导航测试 —— 回归：点击「管理台」应导航到 /admin 并停留，
 * 不得被无-wid 兜底重定向弹回第一个工作区（/admin 为无需 wid 的合法路径）。
 */

import { describe, expect, it } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import MainLayout from './MainLayout'
import { renderProviders } from '@/test/render-providers'
import { mockUser } from '@/test/msw'
import type { UserResponse } from '@/api'

/** 管理台路由桩 —— 展示当前 pathname 供断言 */
function AdminStub() {
    const loc = useLocation()
    return <div data-testid="admin-panel-stub">{loc.pathname}</div>
}

/** 表列表路由桩 */
function TablesStub() {
    return <div data-testid="tables-page-stub">表列表</div>
}

/** 报表路由桩 —— 展示当前 pathname 供断言 */
function ReportsStub() {
    const loc = useLocation()
    return <div data-testid="reports-page-stub">{loc.pathname}</div>
}

/** 按真实路由结构渲染 MainLayout，初始落在第一个工作区的表列表页 */
function renderLayout(authUser: UserResponse) {
    return renderProviders(
        <Routes>
            <Route path="/" element={<MainLayout />}>
                <Route path="w/:wid/tables" element={<TablesStub />} />
                <Route path="w/:wid/reports" element={<ReportsStub />} />
                <Route path="admin" element={<AdminStub />} />
            </Route>
        </Routes>,
        {
            route: '/w/10/tables',
            initialAuth: { user: authUser, token: 'fake-token' },
        },
    )
}

describe('MainLayout 顶部导航', () => {
    it('系统管理员点击「管理台」后到达 /admin，不被重定向回工作区', async () => {
        renderLayout(mockUser)

        // 等待布局加载完成：工作区下拉显示默认工作区名
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 初始在表列表页，点击顶部「管理台」按钮
        // 注：antd 图标 aria-label 会拼进 accessible name（如 'safety管理台'），故用子串正则匹配
        expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        fireEvent.click(screen.getByRole('button', { name: /管理台/ }))

        // 应到达 /admin 管理台页面
        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub')).toHaveTextContent('/admin')
        })
        // 未被无-wid 兜底重定向弹回 /w/10/tables
        expect(screen.queryByTestId('tables-page-stub')).toBeNull()
    })

    it('管理台入口位于右上角用户头像左侧（区别于常规导航区）', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        const adminBtn = screen.getByRole('button', { name: /管理台/ })
        const reportBtn = screen.getByRole('button', { name: /报表/ })
        // 用户菜单触发区含用户名文本
        const userName = screen.getByText('alice')

        // DOM 顺序：报表（常规导航区）→ 管理台 → 用户名（头像区）
        // FOLLOWING(4)：后者在前者之后
        expect(reportBtn.compareDocumentPosition(adminBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(adminBtn.compareDocumentPosition(userName) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('管理台页点击「报表」跳转到最近访问工作区的报表页（而非 /w/undefined/reports）', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 进入管理台（无 wid 上下文），再点击「报表」
        fireEvent.click(screen.getByRole('button', { name: /管理台/ }))
        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub')).toHaveTextContent('/admin')
        })
        fireEvent.click(screen.getByRole('button', { name: /报表/ }))

        // 应回到最近访问的工作区 10 的报表页
        await waitFor(() => {
            expect(screen.getByTestId('reports-page-stub')).toHaveTextContent('/w/10/reports')
        })
    })

    it('非系统管理员不显示「管理台」入口', () => {
        renderLayout({ ...mockUser, role: 'user' })
        expect(screen.queryByRole('button', { name: /管理台/ })).toBeNull()
    })
})

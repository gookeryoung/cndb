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

/** 工作区设置路由桩 —— 展示当前 pathname 供断言 */
function SettingsStub() {
    const loc = useLocation()
    return <div data-testid="settings-page-stub">{loc.pathname}</div>
}

/** 按真实路由结构渲染 MainLayout，初始落在指定路径（默认第一个工作区的表列表页） */
function renderLayout(authUser: UserResponse, route = '/w/10/tables') {
    return renderProviders(
        <Routes>
            <Route path="/" element={<MainLayout />}>
                <Route path="w/:wid/tables" element={<TablesStub />} />
                <Route path="w/:wid/reports" element={<ReportsStub />} />
                <Route path="w/:wid/settings" element={<SettingsStub />} />
                <Route path="admin" element={<AdminStub />} />
            </Route>
        </Routes>,
        {
            route,
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

    it('工作区级按钮已从顶部移除，管理台入口位于右上角用户区左侧', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 「报表」「工作区设置」是工作区级功能，已移入 Content 分页导航，顶部不再保留
        expect(screen.queryByRole('button', { name: /报表/ })).toBeNull()
        expect(screen.queryByTestId('workspace-settings-nav')).toBeNull()

        const adminBtn = screen.getByRole('button', { name: /管理台/ })
        // 右上角用户区优先展示昵称
        const userName = screen.getByText('爱丽丝')

        // DOM 顺序：管理台 → 昵称（头像区）
        // FOLLOWING(4)：后者在前者之后
        expect(adminBtn.compareDocumentPosition(userName) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('Content 分页导航：默认激活「数据资产」，点击 tab 正确导航且激活态随路由变化', async () => {
        renderLayout(mockUser)

        // 初始在表列表页，「数据资产」激活
        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        expect(screen.getByRole('tab', { name: '数据资产' }).closest('.ant-tabs-tab'))
            .toHaveClass('ant-tabs-tab-active')

        // 点击「工作区设置」tab → /w/10/settings
        fireEvent.click(screen.getByRole('tab', { name: '工作区设置' }))
        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        expect(screen.getByRole('tab', { name: '工作区设置' }).closest('.ant-tabs-tab'))
            .toHaveClass('ant-tabs-tab-active')

        // 点击「报表」tab → /w/10/reports
        fireEvent.click(screen.getByRole('tab', { name: '报表' }))
        await waitFor(() => {
            expect(screen.getByTestId('reports-page-stub')).toHaveTextContent('/w/10/reports')
        })
    })

    it('右上角无昵称时回退显示账号名', async () => {
        renderLayout({ ...mockUser, nickname: undefined })

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 昵称为空 → 头像区显示账号名（菜单项同时含账号名，故用 getAllByText）
        expect(screen.getAllByText('alice').length).toBeGreaterThanOrEqual(1)
        expect(screen.queryByText('爱丽丝')).toBeNull()
    })

    it('无工作区上下文（/admin）时不渲染工作区分页导航，避免隐式作用到未知工作区', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 进入管理台（无 wid 上下文，下拉框无当前工作区）
        fireEvent.click(screen.getByRole('button', { name: /管理台/ }))
        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub')).toHaveTextContent('/admin')
        })

        // 分页导航依赖 wid 渲染；无工作区上下文时整体不渲染，侧边栏由「请先从顶部选择一个工作区」提示引导
        expect(screen.queryByRole('tab', { name: '数据资产' })).toBeNull()
        expect(screen.queryByRole('tab', { name: '报表' })).toBeNull()
        expect(screen.queryByRole('tab', { name: '工作区设置' })).toBeNull()
    })

    it('非系统管理员不显示「管理台」入口', () => {
        renderLayout({ ...mockUser, role: 'user' })
        expect(screen.queryByRole('button', { name: /管理台/ })).toBeNull()
    })
})

describe('MainLayout 侧边栏工作区上下文', () => {
    it('进入工作区（有 wid）时渲染数据表导航，不渲染未选择提示', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('sider-tables')).toBeVisible()
        })
        expect(screen.queryByTestId('sider-no-workspace')).toBeNull()
    })

    it('未进入工作区（/admin 无 wid）时侧边栏提示先选工作区，不渲染数据表导航', async () => {
        renderLayout(mockUser, '/admin')

        // 数据表导航以 wid 存在为前提；无 wid 时显示引导提示而非空列表
        await waitFor(() => {
            expect(screen.getByTestId('sider-no-workspace')).toHaveTextContent('请先从顶部选择一个工作区')
        })
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })
})

/**
 * MainLayout 顶部导航测试 —— 回归：点击「管理台」应导航到 /admin 并停留，
 * 不得被无-wid 兜底重定向弹回第一个工作区（/admin 为无需 wid 的合法路径）。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import MainLayout from './MainLayout'
import { useDocOutlineStore } from '@/store/docOutline'
import type { OutlineItem } from '@/components/Document/outline'
import { renderProviders } from '@/test/render-providers'
import { mockUser, mockWorkspace, server } from '@/test/msw'
import type { UserResponse, WorkspaceType } from '@/api'
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

// 个人设置弹窗桩：真实面板会请求 llm 接口且依赖内部状态；
// 桩只暴露 open 与 initialTab，用于验证入口直达「大模型」页签
vi.mock('@/pages/settings/SettingsModal', () => ({
    default: ({ open, initialTab }: { open: boolean; initialTab?: string }) =>
        open ? <div data-testid="settings-modal-stub">{initialTab ?? 'profile'}</div> : null,
}))

/** 管理台路由桩 —— 展示当前 pathname 供断言 */
function AdminStub() {
    const loc = useLocation()
    return <div data-testid="admin-panel-stub">{loc.pathname}</div>
}

/** 帮助文档路由桩 —— 展示当前 pathname 供断言（ADR 0029：整页路由，非抽屉） */
function HelpStub() {
    const loc = useLocation()
    return <div data-testid="help-page-stub">{loc.pathname}</div>
}

/** 表列表路由桩 */
function TablesStub() {
    return <div data-testid="tables-page-stub">表列表</div>
}

/** 网格页路由桩 —— 展示当前 pathname 供断言 */
function GridPageStub() {
    const loc = useLocation()
    return <div data-testid="grid-page-stub">{loc.pathname}</div>
}

/** 表级子页路由桩 —— 修改申请页，展示 pathname 供断言 */
function ChangeRequestsStub() {
    const loc = useLocation()
    return <div data-testid="cr-page-stub">{loc.pathname}</div>
}

/** 表级子页路由桩 —— 数据表设置页，展示 pathname 供断言 */
function TableSettingsStub() {
    const loc = useLocation()
    return <div data-testid="table-settings-stub">{loc.pathname}</div>
}

/** 文档路由桩 —— 展示当前 pathname 供断言 */
function DocumentsStub() {
    const loc = useLocation()
    return <div data-testid="documents-page-stub">{loc.pathname}</div>
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
                {/* 表详情路由桩：点击侧边栏表项会导航到 /w/:wid/tables/:tid，
                    缺少该路由时 react-router 会报 "No routes matched location" */}
                <Route path="w/:wid/tables/:tid" element={<GridPageStub />} />
                <Route path="w/:wid/tables/:tid/change-requests" element={<ChangeRequestsStub />} />
                <Route path="w/:wid/tables/:tid/settings" element={<TableSettingsStub />} />
                <Route path="w/:wid/documents" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/:docId" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/change-requests" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/issues" element={<DocumentsStub />} />
                <Route path="w/:wid/settings" element={<SettingsStub />} />
                <Route path="admin" element={<AdminStub />} />
                <Route path="help" element={<HelpStub />} />
                <Route path="help/:sectionKey/:topicKey" element={<HelpStub />} />
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

        // 「工作区设置」是工作区级功能，已移入 Content 分页导航，顶部不再保留
        expect(screen.queryByTestId('workspace-settings-nav')).toBeNull()

        const adminBtn = screen.getByRole('button', { name: /管理台/ })
        // 右上角用户区优先展示昵称
        const userName = screen.getByText('爱丽丝')

        // DOM 顺序：管理台 → 昵称（头像区）
        // FOLLOWING(4)：后者在前者之后
        expect(adminBtn.compareDocumentPosition(userName) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('Content 分页导航：默认激活「数据表」，点击 tab 正确导航且激活态随路由变化', async () => {
        renderLayout(mockUser)

        // 初始在表列表页，「数据表」激活
        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        // tab 数量徽标：数据表显示表数量（msw 返回 1 张表），文档显示文档数
        await waitFor(() => {
            expect(screen.getByRole('tab', { name: /数据表/ })).toHaveTextContent('1')
        })
        expect(screen.getByRole('tab', { name: /数据表/ }).closest('.ant-tabs-tab'))
            .toHaveClass('ant-tabs-tab-active')

        // 点击「工作区设置」tab → /w/10/settings
        fireEvent.click(screen.getByRole('tab', { name: /工作区设置/ }))
        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        expect(screen.getByRole('tab', { name: /工作区设置/ }).closest('.ant-tabs-tab'))
            .toHaveClass('ant-tabs-tab-active')
    })

    it('分页导航含「文档」页签：位于「工作区设置」之前、带文档数徽标，点击导航到文档模块', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })

        const docsTab = screen.getByRole('tab', { name: /文档/ })
        const settingsTab = screen.getByRole('tab', { name: /工作区设置/ })
        // 文档页签位于工作区设置之前（DOM 顺序约束）
        expect(docsTab.compareDocumentPosition(settingsTab) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

        // 徽标显示文档数（msw 返回 3 个文档）
        await waitFor(() => {
            expect(docsTab).toHaveTextContent('3')
        })

        // 点击导航到 /w/10/documents 且激活态随路由切换
        fireEvent.click(docsTab)
        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        expect(screen.getByRole('tab', { name: /文档/ }).closest('.ant-tabs-tab'))
            .toHaveClass('ant-tabs-tab-active')
    })

    it('分页导航各项均带图标，直观区分入口类型', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        // antd 图标 aria-label 会拼进 accessible name（如 'database数据表'），故用子串正则匹配
        const tabNames = ['数据表', '文档', '工作区设置']
        for (const name of tabNames) {
            const tab = screen.getByRole('tab', { name: new RegExp(name) })
            expect(tab.querySelector('.anticon')).not.toBeNull()
        }
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
        expect(screen.queryByRole('tab', { name: /数据表/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /文档/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /工作区设置/ })).toBeNull()
    })

    it('非系统管理员不显示「管理台」入口', () => {
        renderLayout({ ...mockUser, role: 'user' })
        expect(screen.queryByRole('button', { name: /管理台/ })).toBeNull()
    })

    it('普通用户可打开「关于系统」弹窗查看版本等基本信息', async () => {
        renderLayout({ ...mockUser, role: 'user', is_superuser: false })

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 悬停右上角用户区打开下拉菜单，点击「关于系统」
        fireEvent.mouseEnter(screen.getByText('爱丽丝'))
        fireEvent.click(await screen.findByText('关于系统'))

        // 弹窗渲染基本信息（msw 返回 app_version 0.3.0）；普通用户可见即为本用例回归点
        // AboutModal 为 lazy chunk + 首次请求，放宽等待窗口。
        // 注：jsdom 不触发 transitionend，Modal 进场动画停在 opacity:0，
        // toBeVisible 会误报——沿用项目惯例断言内容存在于已打开的弹窗内
        const verEl = await screen.findByText('0.3.0', {}, { timeout: 5000 })
        expect(verEl.closest('.ant-modal-content')).not.toBeNull()
        expect(screen.getByText('应用名称')).toBeInTheDocument()
        expect(screen.getByText('服务器时间')).toBeInTheDocument()
        expect(screen.queryByText('database_url')).toBeNull()
    })

    it('桌面端品牌字右侧显示应用版本小字', async () => {
        renderLayout(mockUser)

        // 版本与「关于系统」共用 msw 的 /system/about（app_version 0.3.0）
        const version = await screen.findByTestId('app-version')
        expect(version).toHaveTextContent('v0.3.0')
        expect(version).toHaveAttribute('title', '应用版本 v0.3.0')
        expect(version).toHaveClass('cn-brand-version')

        // 位置约束：在 home-logo 内、品牌字「晶格」之后
        const logo = screen.getByTestId('home-logo')
        expect(logo).toContainElement(version)
        const brandWord = logo.querySelector('.cn-brand-word')
        expect(brandWord).not.toBeNull()
        expect(brandWord!.compareDocumentPosition(version) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('版本接口失败时静默不渲染版本小字，顶栏其余功能不受影响', async () => {
        server.use(
            http.get('/api/v1/system/about', () => new HttpResponse(null, { status: 500 })),
        )
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })
        // 非关键信息：不占位、不弹错，页面照常可用
        await waitFor(() => {
            expect(screen.queryByTestId('app-version')).toBeNull()
        })
        expect(screen.getByTestId('tables-page-stub')).toBeVisible()
    })
})

describe('MainLayout 大模型入口', () => {
    it('桌面端顶栏在「帮助文档」左侧提供大模型图标入口，点击直达个人设置「大模型」页签', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        const llmBtn = screen.getByTestId('llm-settings-btn')
        // DOM 顺序：大模型 → 帮助文档（位于帮助左侧）
        expect(
            llmBtn.compareDocumentPosition(screen.getByTestId('help-btn'))
            & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy()

        fireEvent.click(llmBtn)
        await waitFor(() => {
            expect(screen.getByTestId('settings-modal-stub')).toHaveTextContent('llm')
        })
    })

    it('桌面端点击「帮助文档」进入整页 /help，不再弹出抽屉', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })
        expect(screen.getByTestId('help-btn')).toHaveTextContent('帮助文档')

        fireEvent.click(screen.getByTestId('help-btn'))
        await waitFor(() => {
            expect(screen.getByTestId('help-page-stub')).toHaveTextContent('/help')
        })
    })

    it('移动端顶栏不常驻，入口收进用户菜单「大模型设置」并直达页签', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('mobile-nav-btn')).toBeVisible()
        })
        // 顶栏不放常驻按钮，避免挤压本就紧张的移动端空间
        expect(screen.queryByTestId('llm-settings-btn')).toBeNull()
        expect(screen.queryByTestId('help-btn')).toBeNull()

        // 移动端右上角不显示昵称文字，经头像容器触发下拉
        fireEvent.mouseEnter(screen.getByTestId('user-menu-trigger'))
        fireEvent.click(await screen.findByText('大模型设置'))
        await waitFor(() => {
            expect(screen.getByTestId('settings-modal-stub')).toHaveTextContent('llm')
        })
        // 帮助文档同样收进用户菜单，避免顶栏第二个图标
        expect(screen.getByText('帮助文档')).toBeInTheDocument()

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })

    it('移动端点击用户菜单「帮助文档」跳转整页 /help', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        renderLayout(mockUser)

        fireEvent.mouseEnter(screen.getByTestId('user-menu-trigger'))
        fireEvent.click(await screen.findByText('帮助文档'))
        await waitFor(() => {
            expect(screen.getByTestId('help-page-stub')).toHaveTextContent('/help')
        })

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })
})

describe('MainLayout 表级页签（融合导航行）', () => {
    it('表上下文渲染页签区：表名 + 子页页签，替代旧下拉框', async () => {
        renderLayout(mockUser, '/w/10/tables/100')

        await waitFor(() => {
            expect(screen.getByTestId('table-crumb')).toBeVisible()
        })
        // 表名来自 msw 的 mockTable（id=100 客户表）；表列表异步加载，等待其渲染完成
        await waitFor(() => {
            expect(screen.getByTestId('table-crumb-table')).toHaveTextContent('客户表')
        })
        // 三个子页页签已渲染（GitHub 风格页签切换）
        expect(screen.getByTestId('table-tab-change-requests')).toBeVisible()
        expect(screen.getByTestId('table-tab-issues')).toBeVisible()
        expect(screen.getByTestId('table-tab-settings')).toBeVisible()
        // 旧下拉入口与「› 当前位置」文本已移除
        expect(screen.queryByTestId('table-crumb-menu')).toBeNull()
        expect(screen.queryByTestId('table-crumb-current')).toBeNull()
        // 旧表级二级导航行已移除
        expect(screen.queryByTestId('table-subnav-back')).toBeNull()
    })

    it('点击子页页签切换页面：点击「数据表设置」导航到 /w/10/tables/100/settings', async () => {
        renderLayout(mockUser, '/w/10/tables/100')

        await waitFor(() => {
            expect(screen.getByTestId('table-crumb')).toBeVisible()
        })
        fireEvent.click(screen.getByTestId('table-tab-settings'))
        await waitFor(() => {
            expect(screen.getByTestId('table-settings-stub')).toHaveTextContent('/w/10/tables/100/settings')
        })
    })

    it('子页上下文对应页签带选中态，点击表名返回网格', async () => {
        renderLayout(mockUser, '/w/10/tables/100/change-requests')

        // 当前子页页签选中，其余未选中（选中态由 pathname 驱动）
        await waitFor(() => {
            expect(screen.getByTestId('table-tab-change-requests')).toBeVisible()
        })
        expect(screen.getByTestId('table-tab-change-requests')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByTestId('table-tab-settings')).toHaveAttribute('aria-selected', 'false')

        // 点击表名返回网格
        fireEvent.click(screen.getByTestId('table-crumb-table'))
        await waitFor(() => {
            expect(screen.getByTestId('grid-page-stub')).toHaveTextContent('/w/10/tables/100')
        })
    })

    it('非表上下文（表列表页）不渲染页签区', async () => {
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        expect(screen.queryByTestId('table-crumb')).toBeNull()
    })
})

describe('MainLayout 文档区二级导航', () => {
    it('进入文档页显示二级导航：文档根入口 + 修改申请 / 问题清单页签', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        expect(screen.getByTestId('documents-crumb-root')).toBeVisible()
        expect(screen.getByTestId('document-tab-change-requests')).toBeVisible()
        expect(screen.getByTestId('document-tab-issues')).toBeVisible()
        // 未进入表上下文时表级页签不渲染，且文档二级页签默认均未激活
        expect(screen.queryByTestId('table-crumb')).toBeNull()
        expect(screen.getByTestId('document-tab-change-requests')).toHaveAttribute('aria-selected', 'false')
    })

    it('点击「修改申请」页签导航到子页并激活', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        fireEvent.click(screen.getByTestId('document-tab-change-requests'))

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents/change-requests')
        })
        expect(screen.getByTestId('document-tab-change-requests')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByTestId('document-tab-issues')).toHaveAttribute('aria-selected', 'false')
    })

    it('文档编辑器页仍显示二级导航（无子页激活），点击根入口返回文档总览', async () => {
        renderLayout(mockUser, '/w/10/documents/2')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        expect(screen.getByTestId('document-tab-change-requests')).toHaveAttribute('aria-selected', 'false')

        fireEvent.click(screen.getByTestId('documents-crumb-root'))
        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
    })

    it('非文档上下文不渲染文档二级导航', async () => {
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        expect(screen.queryByTestId('documents-crumb')).toBeNull()
    })
})

describe('MainLayout 顶部页签行布局', () => {
    it('窄屏工作区页签保持内容宽度（不被二级页签挤成 0 宽），由整行横滑承载', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 390, height: 844,
        }
        renderLayout(mockUser, '/w/10/tables/100/settings')

        await waitFor(() => {
            expect(screen.getByTestId('table-crumb')).toBeVisible()
        })
        const tabs = document.querySelector('.cn-ws-tabs .ant-tabs') as HTMLElement
        expect(tabs.style.flex).toBe('0 0 auto')

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })

    it('桌面端工作区页签保持可收缩（0 1 auto）', async () => {
        renderLayout(mockUser, '/w/10/tables/100/settings')

        await waitFor(() => {
            expect(screen.getByTestId('table-crumb')).toBeVisible()
        })
        const tabs = document.querySelector('.cn-ws-tabs .ant-tabs') as HTMLElement
        expect(tabs.style.flex).toBe('0 1 auto')
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

    it('管理台（/admin 无 wid）不渲染工作区侧栏：导航交给管理台页内分区栏', async () => {
        renderLayout(mockUser, '/admin')

        // 管理台没有工作区语义，侧栏只会剩「请先选择工作区」的空占位 →
        // 整个 Sider 不再渲染，内容区拿到整幅宽度
        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub')).toHaveTextContent('/admin')
        })
        expect(document.querySelector('.ant-layout-sider')).toBeNull()
        expect(screen.queryByTestId('sider-no-workspace')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })
})

describe('MainLayout 移动端适配', () => {
    beforeEach(() => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
    })

    it('移动端渲染汉堡入口，且不渲染常驻 Sider', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('mobile-nav-btn')).toBeVisible()
        })
        // Sider 整体未渲染：DOM 中无 ant-layout-sider
        expect(document.querySelector('.ant-layout-sider')).toBeNull()
    })

    it('点击汉堡打开抽屉导航，点击表项后自动收起', async () => {
        renderLayout(mockUser)

        fireEvent.click(screen.getByTestId('mobile-nav-btn'))
        // 抽屉打开：出现共享的表导航内容（msw 默认返回 1 张表，分组标题为「数据表 (N)」）
        expect(await screen.findByText('数据表 (1)')).toBeVisible()

        // 抽屉内点击「客户表」→ 触发导航并自动收起抽屉
        // 注：antd Drawer 关闭后内容仍留在 DOM（无 destroyOnHidden），
        // 用 open 状态类消失判定收起，而非文本移除
        fireEvent.click(await screen.findByText('客户表'))
        await waitFor(() => {
            expect(document.querySelector('.ant-drawer-open')).toBeNull()
        })
    })

    it('移动端隐藏品牌文字与管理台/帮助按钮文字，仅保留图标', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('mobile-nav-btn')).toBeVisible()
        })
        // 品牌文字隐藏（icon 仍渲染），版本小字随品牌字一起隐藏
        expect(screen.queryByText('cndb')).toBeNull()
        expect(screen.queryByTestId('app-version')).toBeNull()
        // 工作区下拉仅图标：按钮内无「测试工作区」文字
        expect(screen.queryByRole('button', { name: /测试工作区/ })).toBeNull()

        // 复位为桌面端：responsiveState 是模块级变量，泄漏会让后续用例按移动端渲染
        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })
})

// ─────────────── 工作区类型门控：页签 / 侧栏 / 落地页 ───────────────

/** 覆盖工作区列表接口，返回指定类型的工作区 */
function useWorkspaceType(type: WorkspaceType) {
    server.use(
        http.get('/api/v1/workspaces', () =>
            HttpResponse.json([{ ...mockWorkspace, workspace_type: type }])),
    )
}

describe('MainLayout 工作区类型门控', () => {
    it('数据类工作区（data）不显示「文档」页签', async () => {
        useWorkspaceType('data')
        renderLayout(mockUser)

        await waitFor(() => expect(screen.getByTestId('tables-page-stub')).toBeVisible())
        await waitFor(() => expect(screen.queryByRole('tab', { name: /文档/ })).toBeNull())
        expect(screen.getByRole('tab', { name: /数据表/ })).toBeInTheDocument()
    })

    it('文档类工作区（doc）仅显示「文档」与「工作区设置」，侧栏切换为文档导航', async () => {
        useWorkspaceType('doc')
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('documents-page-stub')).toBeVisible())
        await waitFor(() => expect(screen.queryByRole('tab', { name: /数据表/ })).toBeNull())

        expect(screen.queryByRole('tab', { name: /数据分析/ })).toBeNull()
        expect(screen.getByRole('tab', { name: /文档/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /工作区设置/ })).toBeInTheDocument()
        // 无数据表功能 → 文档段渲染文档导航侧栏（需求 0065），无表导航
        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('文档类工作区访问数据表/数据分析路径自动重定向到文档页', async () => {
        useWorkspaceType('doc')
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        expect(screen.queryByTestId('tables-page-stub')).toBeNull()
    })
})

// ─────────────── 侧边栏随功能段切换（需求 0065） ───────────────

describe('MainLayout 侧边栏随功能段切换（需求 0065）', () => {
    afterEach(() => {
        useDocOutlineStore.setState({ outline: [] })
    })

    it('文档列表页：侧栏显示文档列表（不含文件夹），不再渲染数据表列表', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        // 数据表导航在文档段不渲染
        expect(screen.queryByTestId('sider-tables')).toBeNull()
        // 列出非文件夹文档（msw：需求说明 1 篇 + 产品文档/会议纪要 2 个文件夹被过滤）
        await waitFor(() => expect(screen.getByTestId('sider-documents-count')).toHaveTextContent('文档 (1)'))
        expect(screen.getByText('需求说明')).toBeVisible()
        // 文件夹不进入侧栏列表
        expect(screen.queryByText('产品文档')).toBeNull()
    })

    it('点击侧栏文档项导航到对应文档编辑器', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByText('需求说明')).toBeVisible())
        fireEvent.click(screen.getByText('需求说明'))
        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents/2')
        })
    })

    it('文档编辑器段：侧栏显示文档结构大纲（来自编辑器同步的 store），无表导航与文档列表', async () => {
        const outline: OutlineItem[] = [
            { level: 1, text: '概述', anchor: 'doc-h-概述', line: 0 },
            { level: 2, text: '背景', anchor: 'doc-h-背景', line: 4 },
        ]
        useDocOutlineStore.setState({ outline })
        renderLayout(mockUser, '/w/10/documents/2')

        await waitFor(() => expect(screen.getByTestId('sider-doc-outline')).toBeVisible())
        expect(screen.getByText('文档结构')).toBeVisible()
        expect(screen.getByText('概述')).toBeVisible()
        expect(screen.getByText('背景')).toBeVisible()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
        expect(screen.queryByTestId('sider-documents')).toBeNull()
    })

    it('大纲 store 为空（如刚进入编辑器未解析）时显示空态提示', async () => {
        renderLayout(mockUser, '/w/10/documents/2')

        await waitFor(() => expect(screen.getByTestId('sider-doc-outline')).toBeVisible())
        expect(screen.getByText(/暂无标题/)).toBeVisible()
    })

    it('点击大纲条目派发锚点跳转事件，由编辑器消费定位', async () => {
        const outline: OutlineItem[] = [{ level: 1, text: '概述', anchor: 'doc-h-概述', line: 0 }]
        useDocOutlineStore.setState({ outline })
        const dispatched: string[] = []
        const handler = (e: Event) => dispatched.push((e as CustomEvent<string>).detail)
        window.addEventListener('doc-outline-jump', handler)

        renderLayout(mockUser, '/w/10/documents/2')
        await waitFor(() => expect(screen.getByText('概述')).toBeVisible())
        fireEvent.click(screen.getByText('概述'))
        expect(dispatched).toEqual(['doc-h-概述'])
        window.removeEventListener('doc-outline-jump', handler)
    })

    it('工作区设置段：不渲染任何侧栏，内容区占满宽度', async () => {
        renderLayout(mockUser, '/w/10/settings')

        await waitFor(() => expect(screen.getByTestId('settings-page-stub')).toBeVisible())
        expect(document.querySelector('.ant-layout-sider')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
        expect(screen.queryByTestId('sider-documents')).toBeNull()
    })

    it('数据表段维持表导航：数据表列表侧栏不受文档段切换影响', async () => {
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => expect(screen.getByTestId('sider-tables')).toBeVisible())
        expect(screen.queryByTestId('sider-documents')).toBeNull()
        expect(screen.queryByTestId('sider-doc-outline')).toBeNull()
    })

    it('移动端文档段：抽屉导航显示文档列表而非表列表', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        renderLayout(mockUser, '/w/10/documents')

        fireEvent.click(screen.getByTestId('mobile-nav-btn'))
        await waitFor(() => {
            expect(screen.getByTestId('sider-documents-count')).toHaveTextContent('文档 (1)')
        })
        expect(screen.queryByText('数据表 (')).toBeNull()

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })
})

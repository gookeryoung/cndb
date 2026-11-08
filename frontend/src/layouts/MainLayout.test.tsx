/**
 * MainLayout 顶部导航测试 —— 回归：点击「管理台」应导航到 /admin 并停留，
 * 不得被无-wid 兜底重定向弹回第一个工作区（/admin 为无需 wid 的合法路径）。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import MainLayout from './MainLayout'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, mockWorkspace, server } from '@/test/msw'
import type { UserResponse, WorkspaceModule } from '@/api'
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

/** 管理台路由桩 —— 展示当前 pathname + search 供断言 */
function AdminStub() {
    const loc = useLocation()
    return <div data-testid="admin-panel-stub">{loc.pathname}{loc.search}</div>
}

/** 主页路由桩（/w 工作区列表，需求 0081 C3 主页搜索） */
function HomeStub() {
    return <div data-testid="home-page-stub">主页</div>
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

/** 工作区级问题清单路由桩 —— 展示 pathname 供断言 */
function IssuesPageStub() {
    const loc = useLocation()
    return <div data-testid="issues-page-stub">{loc.pathname}</div>
}

/** 表级子页路由桩 —— 数据表设置页，展示 pathname 供断言 */
function TableSettingsStub() {
    const loc = useLocation()
    return <div data-testid="table-settings-stub">{loc.pathname}</div>
}

/** 设计列表路由桩（ADR 0080：仅勾选设计的工作区落地段）；展示 search 供大纲定位断言 */
function DesignsStub() {
    const loc = useLocation()
    return <div data-testid="designs-page-stub">{loc.pathname}{loc.search}</div>
}

/** 文档路由桩 —— 展示当前 pathname + query 供断言（?parent= 落在 search 上） */
function DocumentsStub() {
    const loc = useLocation()
    return <div data-testid="documents-page-stub">{loc.pathname}{loc.search}</div>
}

/** 工作区统计路由桩 —— 一级导航「统计」/w/:wid/stats（展示 search 供分项断言） */
function StatsStub() {
    const loc = useLocation()
    return <div data-testid="stats-page-stub">{loc.pathname}{loc.search}</div>
}

/** 工作区设置路由桩 —— 展示当前 pathname + query 供断言（分项由 ?section= 驱动） */
function SettingsStub() {
    const loc = useLocation()
    return <div data-testid="settings-page-stub">{loc.pathname}{loc.search}</div>
}

/** 分析 / 同步 / 质量检查路由桩 —— 展示当前 pathname 供断言 */
function WsSectionStub() {
    const loc = useLocation()
    return <div data-testid="ws-section-stub">{loc.pathname}</div>
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
                <Route path="w/:wid/tables/change-requests" element={<ChangeRequestsStub />} />
                <Route path="w/:wid/tables/issues" element={<IssuesPageStub />} />
                <Route path="w/:wid/tables/:tid/change-requests" element={<ChangeRequestsStub />} />
                <Route path="w/:wid/tables/:tid/settings" element={<TableSettingsStub />} />
                <Route path="w/:wid/design" element={<DesignsStub />} />
                <Route path="w/:wid/design/:designId" element={<DesignsStub />} />
                <Route path="w/:wid/documents" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/:docId" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/change-requests" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/issues" element={<DocumentsStub />} />
                {/* 文档质量检查：入口留在文档上下文（静态段优先于 :docId） */}
                <Route path="w/:wid/documents/pipelines" element={<DocumentsStub />} />
                <Route path="w/:wid/documents/pipelines/:rid" element={<DocumentsStub />} />
                <Route path="w/:wid/stats" element={<StatsStub />} />
                <Route path="w/:wid/settings" element={<SettingsStub />} />
                <Route path="w/:wid/analytics" element={<WsSectionStub />} />
                <Route path="w/:wid/datasource" element={<WsSectionStub />} />
                <Route path="w/:wid/pipelines" element={<WsSectionStub />} />
                <Route path="w" element={<HomeStub />} />
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

    it('顶栏布局：搜索框位于右侧操作按钮左侧，主页 / 工作区位置一致（0081 C1 调整）', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 左区（品牌 + 工作区 + 一级导航）先于右区（需求 0081 C1）
        const left = document.querySelector('.cn-header-left')
        const right = document.querySelector('.cn-header-right')
        expect(left).not.toBeNull()
        expect(right).not.toBeNull()
        expect(left!.compareDocumentPosition(right!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(left!.querySelector('[data-testid="ws-module-nav"]')).not.toBeNull()

        // 搜索框收进右区首位（不再占中区剩余空间，避免主页 / 工作区两视图位置漂移）
        const search = right!.querySelector('.cn-header-search')
        expect(search).not.toBeNull()
        expect(left!.querySelector('.cn-header-search')).toBeNull()
        expect(search!.compareDocumentPosition(screen.getByTestId('llm-settings-btn'))
            & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

        // 右区操作按钮 DOM 顺序不变：大模型 → 帮助 → 管理台 → 用户头像（C2）
        const adminBtn = screen.getByRole('button', { name: /管理台/ })
        const userTrigger = screen.getByTestId('user-menu-trigger')
        expect(adminBtn.compareDocumentPosition(userTrigger) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('顶栏一级导航：默认激活「数据表」（带表数徽标），点击「工作区设置」导航且激活态随路由变化', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        // 徽标显示表数量（msw 返回 1 张表）
        await waitFor(() => {
            expect(screen.getByTestId('ws-nav-tables')).toHaveTextContent('1')
        })
        expect(screen.getByTestId('ws-nav-tables')).toHaveAttribute('aria-current', 'page')

        // 点击「工作区设置」→ /w/10/settings（一级模块上移顶栏，需求 0081 C4）
        fireEvent.click(screen.getByTestId('ws-nav-settings'))
        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        expect(screen.getByTestId('ws-nav-settings')).toHaveAttribute('aria-current', 'page')
        expect(screen.getByTestId('ws-nav-tables')).not.toHaveAttribute('aria-current')
    })

    it('顶栏一级导航含「文档」：位于「工作区设置」之前、带文档数徽标，点击导航到文档模块', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })

        const docsNav = screen.getByTestId('ws-nav-documents')
        const settingsNav = screen.getByTestId('ws-nav-settings')
        // 文档导航位于工作区设置之前（DOM 顺序约束）
        expect(docsNav.compareDocumentPosition(settingsNav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

        // 徽标显示文档数（msw 返回 3 个文档）
        await waitFor(() => {
            expect(docsNav).toHaveTextContent('3')
        })

        // 点击导航到 /w/10/documents 且激活态随路由切换
        fireEvent.click(docsNav)
        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        expect(screen.getByTestId('ws-nav-documents')).toHaveAttribute('aria-current', 'page')
    })

    it('顶栏一级导航「设计」带设计数徽标，点击导航到设计模块', async () => {
        server.use(http.get('/api/v1/workspaces/:wid/designs', () =>
            HttpResponse.json([
                { id: 20, workspace_id: 10, title: '四轮小车', kind: 'assembly' },
                { id: 21, workspace_id: 10, title: '法兰板', kind: 'part' },
            ])))
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })

        // 徽标显示设计数（与数据表 / 文档同口径，0 也显示）
        const designNav = screen.getByTestId('ws-nav-design')
        await waitFor(() => {
            expect(designNav).toHaveTextContent('2')
        })

        // 点击导航到 /w/10/design 且激活态随路由切换
        fireEvent.click(designNav)
        await waitFor(() => {
            expect(screen.getByTestId('designs-page-stub')).toHaveTextContent('/w/10/design')
        })
        expect(screen.getByTestId('ws-nav-design')).toHaveAttribute('aria-current', 'page')
    })

    it('顶栏一级导航各项均带图标，直观区分入口类型', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        const navIds = ['ws-nav-tables', 'ws-nav-documents', 'ws-nav-design', 'ws-nav-stats', 'ws-nav-settings']
        for (const id of navIds) {
            expect(screen.getByTestId(id).querySelector('.anticon')).not.toBeNull()
        }
    })

    it('统计为一级导航入口，位于工作区设置左侧并可跳转', async () => {
        renderLayout(mockUser)

        await waitFor(() => expect(screen.getByTestId('tables-page-stub')).toBeVisible())

        const nav = screen.getByTestId('ws-module-nav')
        const statsNav = screen.getByTestId('ws-nav-stats')
        const settingsNav = screen.getByTestId('ws-nav-settings')
        expect(statsNav).toHaveTextContent('统计')
        // 顺序：统计紧邻工作区设置左侧
        expect(statsNav.nextElementSibling).toBe(settingsNav)
        expect(nav.contains(statsNav)).toBe(true)

        fireEvent.click(statsNav)
        await waitFor(() => {
            expect(screen.getByTestId('stats-page-stub')).toHaveTextContent('/w/10/stats')
        })
        expect(screen.getByTestId('ws-nav-stats')).toHaveAttribute('aria-current', 'page')
    })

    it('统计段侧栏为统计分项：第一行概览、第二行贡献统计，点击由 ?section= 驱动', async () => {
        renderLayout(mockUser)

        await waitFor(() => expect(screen.getByTestId('tables-page-stub')).toBeVisible())
        fireEvent.click(screen.getByTestId('ws-nav-stats'))
        await waitFor(() => expect(screen.getByTestId('sider-stats')).toBeVisible())

        const sider = screen.getByTestId('sider-stats')
        const items = sider.querySelectorAll('.ant-menu-item')
        expect(items).toHaveLength(2)
        expect(items[0]).toHaveTextContent('概览')
        expect(items[1]).toHaveTextContent('贡献统计')
        // 缺省选中第一行「概览」
        expect(items[0]).toHaveClass('ant-menu-item-selected')

        fireEvent.click(items[1])
        await waitFor(() => {
            expect(screen.getByTestId('stats-page-stub'))
                .toHaveTextContent('/w/10/stats?section=contribution')
        })
        expect(sider.querySelectorAll('.ant-menu-item')[1]).toHaveClass('ant-menu-item-selected')
    })

    it('右上角仅保留头像图标：昵称/账号名不再展示在顶栏（仅存在于用户菜单）', async () => {
        renderLayout({ ...mockUser, nickname: undefined })

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // GitHub 风格：顶栏用户区只渲染头像圆形按钮，昵称/账号名文字一律收进菜单与 Tooltip
        expect(screen.queryByText('爱丽丝')).toBeNull()
        // 账号名仅出现在下拉菜单项中（先悬停头像打开菜单再断言）
        fireEvent.mouseEnter(screen.getByTestId('user-menu-trigger'))
        expect(await screen.findByText('alice')).toBeInTheDocument()
    })

    it('无工作区上下文（/admin）时不渲染一级导航与二级页签，顶栏搜索切换为主页模式', async () => {
        renderLayout(mockUser)

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /测试工作区/ })).toBeVisible()
        })

        // 进入管理台（无 wid 上下文，下拉框无当前工作区）
        fireEvent.click(screen.getByRole('button', { name: /管理台/ }))
        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub')).toHaveTextContent('/admin')
        })

        // 一级导航与二级页签均依赖 wid 渲染；无工作区上下文时整体不渲染，
        // 侧边栏由「请先从顶部选择一个工作区」提示引导
        expect(screen.queryByTestId('ws-module-nav')).toBeNull()
        expect(screen.queryByTestId('ws-nav-tables')).toBeNull()
        expect(screen.queryByTestId('ws-nav-settings')).toBeNull()
        expect(screen.queryByRole('tab', { name: /数据分析/ })).toBeNull()
        // 主页模式搜索（0081 C3）：进入工作区前也可搜索，范围=全部工作区
        expect(screen.getByTestId('global-search-input')).toHaveAttribute('aria-label', '搜索全部工作区')
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

        // 悬停右上角用户头像打开下拉菜单，点击「关于系统」
        fireEvent.mouseEnter(screen.getByTestId('user-menu-trigger'))
        fireEvent.click(await screen.findByText('关于系统'))

        // 弹窗渲染基本信息（msw 返回 app_version 0.3.0）；普通用户可见即为本用例回归点
        // AboutModal 为 lazy chunk + 首次请求，放宽等待窗口。
        // 注：jsdom 不触发 transitionend，Modal 进场动画停在 opacity:0，
        // toBeVisible 会误报——沿用项目惯例断言内容存在于已打开的弹窗内
        const verEl = await screen.findByText('0.3.0', {}, { timeout: 5000 })
        // antd 6：Modal 内容容器类由 .ant-modal-content 改为 .ant-modal-container
        expect(verEl.closest('.ant-modal-container')).not.toBeNull()
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

        // 位置约束：在 home-logo 内、品牌字「晶格协同」之后
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

// ─────────────── 顶栏一级导航 / 主页搜索 / 二级页签（需求 0081） ───────────────

describe('MainLayout 顶栏导航重构（需求 0081）', () => {
    it('桌面端内容区页签仅承载二级模块：一级模块不在页签行（C4/C5）', async () => {
        renderLayout(mockUser)

        await waitFor(() => expect(screen.getByTestId('tables-page-stub')).toBeVisible())
        // 「数据列表」为数据表一级导航的第一个二级页签，进入数据表模块默认激活（数据列表视图即 /tables）
        const listTab = screen.getByRole('tab', { name: /数据列表/ })
        expect(listTab).toBeInTheDocument()
        expect(listTab).toHaveAttribute('aria-selected', 'true')
        // 二级模块维持在内容区上方页签行（原位置不动）
        expect(screen.getByRole('tab', { name: /数据分析/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /数据同步/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /质量检查/ })).toBeInTheDocument()
        // 页签顺序：数据列表 → 数据分析 → 数据同步 → 质量检查 → 修改申请 → 问题清单
        const tabLabels = within(document.querySelector('.cn-ws-tabs') as HTMLElement)
            .getAllByRole('tab')
            .map(tab => (tab.textContent ?? '').trim())
        expect(tabLabels).toEqual(['数据列表', '数据分析', '数据同步', '质量检查', '修改申请', '问题清单'])
        // 一级模块已上移顶栏，不再出现在页签行
        expect(screen.queryByRole('tab', { name: /数据表/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /文档/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /设计/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /工作区设置/ })).toBeNull()
    })

    it('落在质量检查段时页签行保持数据分析与数据同步（与数据分析行为一致）', async () => {
        // 质量检查同为数据表段内的二级功能：切到 /pipelines 不收敛页签行
        renderLayout(mockUser, '/w/10/pipelines')
        await waitFor(() => expect(screen.getByTestId('ws-section-stub')).toBeVisible())
        expect(screen.getByRole('tab', { name: /数据分析/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /数据同步/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /质量检查/ })).toBeInTheDocument()
    })

    it('切到工作区设置时页签行不渲染质量检查', async () => {
        renderLayout(mockUser, '/w/10/settings')
        await waitFor(() => expect(screen.getByTestId('settings-page-stub')).toBeVisible())
        expect(screen.queryByRole('tab', { name: /质量检查/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /数据分析/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /数据同步/ })).toBeNull()
        // 页签行整体收敛，不留空页签栏
        expect(document.querySelector('.cn-ws-tabs .ant-tabs')).toBeNull()
    })

    it('切到文档/设计模块时页签行隐藏数据分析、数据同步与质量检查', async () => {
        // 数据分析 / 数据同步为数据表派生二级功能，仅数据表上下文显示
        const { unmount } = renderLayout(mockUser, '/w/10/documents')
        await waitFor(() => expect(screen.getByTestId('documents-page-stub')).toBeVisible())
        expect(screen.queryByRole('tab', { name: /数据分析/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /数据同步/ })).toBeNull()
        // 数据列表为数据表段专属二级页签，切到文档模块后隐藏
        expect(screen.queryByRole('tab', { name: /数据列表/ })).toBeNull()
        // 文档上下文二级页签为空：整个空 Tabs（含 tablist）不渲染，避免空页签栏留白；
        // 质量检查入口由文档区胶囊页签承载
        expect(document.querySelector('.cn-ws-tabs .ant-tabs')).toBeNull()
        expect(screen.getByTestId('document-tab-pipelines')).toBeVisible()
        unmount()

        // 设计段同样收敛：质量检查为数据表域入口，设计模块不再渲染（2026-11-02 用户口径）
        renderLayout(mockUser, '/w/10/design')
        await waitFor(() => expect(screen.getByTestId('designs-page-stub')).toBeVisible())
        expect(screen.queryByRole('tab', { name: /数据分析/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /数据同步/ })).toBeNull()
        expect(screen.queryByRole('tab', { name: /质量检查/ })).toBeNull()
        // 设计区二级页签（0083 C1）：唯一入口「设计结构」，落在模块根页时激活
        expect(screen.getByTestId('design-crumb')).toBeVisible()
        expect(screen.getByTestId('design-tab-structure')).toHaveAttribute('aria-selected', 'true')
    })

    it('设计编辑器页仍选中「设计结构」子页（ADR 0109 D1）', async () => {
        renderLayout(mockUser, '/w/10/design/20')
        await waitFor(() => expect(screen.getByTestId('designs-page-stub')).toHaveTextContent('/w/10/design/20'))
        expect(screen.getByTestId('design-crumb')).toBeVisible()
        expect(screen.getByTestId('design-tab-structure')).toHaveAttribute('aria-selected', 'true')
    })

    it('主页（/w）顶栏渲染全局搜索：进入工作区前也可搜索（C3）', async () => {
        renderLayout(mockUser, '/w')

        await waitFor(() => expect(screen.getByTestId('home-page-stub')).toBeVisible())
        // 主页模式：无范围选择器、aria-label 口径为全部工作区
        expect(screen.getByTestId('global-search-input')).toHaveAttribute('aria-label', '搜索全部工作区')
        expect(screen.queryByTestId('global-search-scope')).toBeNull()
        // 主页无工作区上下文：一级导航不渲染
        expect(screen.queryByTestId('ws-module-nav')).toBeNull()
    })

    it('移动端一级模块维持在页签行全量渲染，顶栏不渲染一级导航（C5）', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        renderLayout(mockUser)

        await waitFor(() => expect(screen.getByTestId('mobile-nav-btn')).toBeVisible())
        // 顶栏放不下四个一级模块：维持页签行全量承载（移动端形态不变）
        expect(screen.queryByTestId('ws-module-nav')).toBeNull()
        expect(screen.getByRole('tab', { name: /数据表/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /文档/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /设计/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /工作区设置/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /数据分析/ })).toBeInTheDocument()
        // 数据列表仅桌面端渲染：移动端页签行一级模块「数据表」已承载入口，不重复出现
        expect(screen.queryByRole('tab', { name: /数据列表/ })).toBeNull()

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
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
        // GitHub 风格图标按钮：无文字，说明收进 aria-label / Tooltip
        expect(screen.getByTestId('help-btn')).toHaveAttribute('aria-label', '帮助文档')

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

describe('MainLayout 表级导航（2026-11-03 取消）', () => {
    it('选中单个数据表时不再渲染表名 / 数据表设置入口 / 分隔符', async () => {
        renderLayout(mockUser, '/w/10/tables/100')

        await waitFor(() => {
            expect(screen.getByTestId('grid-page-stub')).toHaveTextContent('/w/10/tables/100')
        })
        expect(screen.queryByTestId('table-crumb')).toBeNull()
        expect(screen.queryByTestId('table-tab-settings')).toBeNull()
        expect(document.querySelector('.cn-table-crumb-divider')).toBeNull()
        // 表列表 / 工作区级页签仍正常
        expect(screen.getByRole('tab', { name: /数据列表/ })).toBeInTheDocument()
    })

    it('数据表设置路由仍可直接访问（只是入口从导航移除）', async () => {
        renderLayout(mockUser, '/w/10/tables/100/settings')

        await waitFor(() => {
            expect(screen.getByTestId('table-settings-stub')).toHaveTextContent('/w/10/tables/100/settings')
        })
        expect(screen.queryByTestId('table-crumb')).toBeNull()
    })

    it('数据表模块工作区级渲染「修改申请 / 问题清单」页签并可切换', async () => {
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => {
            expect(screen.getByText('修改申请')).toBeVisible()
            expect(screen.getByText('问题清单')).toBeVisible()
        })
        fireEvent.click(screen.getByText('修改申请'))
        await waitFor(() => {
            expect(screen.getByTestId('cr-page-stub')).toHaveTextContent('/w/10/tables/change-requests')
        })
        expect(screen.queryByTestId('table-crumb')).toBeNull()
        fireEvent.click(screen.getByText('问题清单'))
        await waitFor(() => {
            expect(screen.getByTestId('issues-page-stub')).toHaveTextContent('/w/10/tables/issues')
        })
    })

    it('非表上下文（表列表页）不渲染表级导航', async () => {
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        expect(screen.queryByTestId('table-crumb')).toBeNull()
    })
})

describe('MainLayout 文档区二级导航', () => {
    it('进入文档页显示二级导航：文档结构 / 质量检查 / 修改申请 / 问题清单页签', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        expect(screen.getByTestId('document-tab-structure')).toBeVisible()
        expect(screen.getByTestId('document-tab-pipelines')).toBeVisible()
        expect(screen.getByTestId('document-tab-change-requests')).toBeVisible()
        expect(screen.getByTestId('document-tab-issues')).toBeVisible()
        // 未进入表上下文时表级页签不渲染
        expect(screen.queryByTestId('table-crumb')).toBeNull()
        // 「文档结构」即文档总览列表页本体：落在 /documents 时激活（0082 C4）
        expect(screen.getByTestId('document-tab-structure')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByTestId('document-tab-change-requests')).toHaveAttribute('aria-selected', 'false')
        // 二级页签为空时不渲染空 Tabs：避免空页签栏内边距在胶囊页签左侧留出空白
        expect(document.querySelector('.cn-ws-tabs .ant-tabs')).toBeNull()
    })

    it('编辑器页「文档结构」未激活，点击后返回文档总览并激活（0082 C4）', async () => {
        renderLayout(mockUser, '/w/10/documents/2')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        expect(screen.getByTestId('document-tab-structure')).toHaveAttribute('aria-selected', 'false')
        fireEvent.click(screen.getByTestId('document-tab-structure'))

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        expect(screen.getByTestId('document-tab-structure')).toHaveAttribute('aria-selected', 'true')
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

    it('文档编辑器页仍显示二级导航（无子页激活），点击「质量检查」留在文档上下文并激活', async () => {
        renderLayout(mockUser, '/w/10/documents/2')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        expect(screen.getByTestId('document-tab-change-requests')).toHaveAttribute('aria-selected', 'false')

        fireEvent.click(screen.getByTestId('document-tab-pipelines'))
        await waitFor(() => {
            // 文档质量检查不跳到工作区级 /pipelines：仍留在文档区（/documents/pipelines）
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents/pipelines')
        })
        expect(screen.queryByTestId('ws-section-stub')).toBeNull()
        expect(screen.getByTestId('documents-crumb')).toBeVisible()
        expect(screen.getByTestId('document-tab-pipelines')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByTestId('document-tab-structure')).toHaveAttribute('aria-selected', 'false')
    })

    it('直接落在文档质量检查页时「质量检查」页签激活', async () => {
        renderLayout(mockUser, '/w/10/documents/pipelines')

        await waitFor(() => {
            expect(screen.getByTestId('documents-crumb')).toBeVisible()
        })
        expect(screen.getByTestId('document-tab-pipelines')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByTestId('document-tab-structure')).toHaveAttribute('aria-selected', 'false')
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
            expect(screen.getByTestId('table-settings-stub')).toHaveTextContent('/w/10/tables/100/settings')
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
            expect(screen.getByTestId('table-settings-stub')).toHaveTextContent('/w/10/tables/100/settings')
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

    it('管理台（/admin 无 wid）侧栏列出管理台分项，不渲染工作区导航', async () => {
        renderLayout(mockUser, '/admin')

        // 管理台没有工作区语义：侧栏与工作区设置 / 统计同形，列管理台分项
        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub')).toHaveTextContent('/admin')
        })
        expect(screen.getByTestId('sider-admin')).toBeVisible()
        expect(screen.getByText('系统管理台')).toBeVisible()
        expect(screen.queryByTestId('sider-no-workspace')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('管理台侧栏切换分项写入 ?section= 并保留事件流筛选参数', async () => {
        renderLayout(mockUser, '/admin?section=events&action=auth.login')

        await waitFor(() => {
            expect(screen.getByTestId('sider-admin')).toBeVisible()
        })
        fireEvent.click(screen.getByRole('menuitem', { name: /用户管理/ }))

        await waitFor(() => {
            expect(screen.getByTestId('admin-panel-stub').textContent).toContain('section=users')
        })
        expect(screen.getByTestId('admin-panel-stub').textContent).toContain('action=auth.login')
    })

    it('管理台侧栏分项选中态由 ?section= 驱动', async () => {
        renderLayout(mockUser, '/admin?section=storage')

        await waitFor(() => {
            expect(screen.getByTestId('sider-admin')).toBeVisible()
        })
        const selected = document.querySelector('.cn-table-nav .ant-menu-item-selected')
        expect(selected).toHaveTextContent('空间分配')
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

// ─────────────── 工作区模块门控：页签 / 侧栏 / 落地页（ADR 0080） ───────────────

/** 覆盖工作区列表接口，返回指定勾选模块的工作区 */
function useWorkspaceModules(modules: WorkspaceModule[]) {
    server.use(
        http.get('/api/v1/workspaces', () =>
            HttpResponse.json([{ ...mockWorkspace, modules }])),
    )
}

/** 覆盖工作区列表接口：返回当前工作区（全三模块）+ 目标工作区（指定模块），用于切换断言 */
function useSwitchTarget(targetModules: WorkspaceModule[]) {
    server.use(
        http.get('/api/v1/workspaces', () => HttpResponse.json([
            { ...mockWorkspace, id: 10, name: '测试工作区', modules: ['tables', 'documents', 'design'] },
            { ...mockWorkspace, id: 20, name: '目标工作区', modules: targetModules },
        ])),
    )
}

/** 打开顶栏工作区下拉并选中「目标工作区」 */
async function switchToTargetWorkspace() {
    fireEvent.click(screen.getByTestId('ws-switch-btn'))
    fireEvent.click(await screen.findByText('目标工作区'))
}

describe('MainLayout 工作区模块门控', () => {
    it('仅勾选数据表的工作区不显示「文档/设计」一级导航，数据分析与数据同步随表开放', async () => {
        useWorkspaceModules(['tables'])
        renderLayout(mockUser)

        await waitFor(() => expect(screen.getByTestId('tables-page-stub')).toBeVisible())
        await waitFor(() => expect(screen.queryByTestId('ws-nav-documents')).toBeNull())
        expect(screen.queryByTestId('ws-nav-design')).toBeNull()
        expect(screen.getByTestId('ws-nav-tables')).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /数据分析/ })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: /数据同步/ })).toBeInTheDocument()
    })

    it('仅勾选文档的工作区仅显示「文档/工作区设置」一级导航，侧栏切换为文档导航', async () => {
        useWorkspaceModules(['documents'])
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('documents-page-stub')).toBeVisible())
        await waitFor(() => expect(screen.queryByTestId('ws-nav-tables')).toBeNull())
        expect(screen.queryByRole('tab', { name: /数据分析/ })).toBeNull()

        expect(screen.getByTestId('ws-nav-documents')).toBeInTheDocument()
        expect(screen.getByTestId('ws-nav-settings')).toBeInTheDocument()
        // 文档上下文二级页签为空：空 Tabs 不渲染（避免空页签栏留白），入口由文档区胶囊页签承载
        expect(document.querySelector('.cn-ws-tabs .ant-tabs')).toBeNull()
        expect(screen.getByTestId('document-tab-pipelines')).toBeVisible()
        // 无数据表功能 → 文档段渲染文档导航侧栏（需求 0065），无表导航
        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('仅勾选设计的工作区落地 /design，页签行不渲染质量检查', async () => {
        useWorkspaceModules(['design'])
        renderLayout(mockUser, '/w/10/design')

        await waitFor(() => expect(screen.getByTestId('designs-page-stub')).toBeVisible())
        await waitFor(() => expect(screen.queryByTestId('ws-nav-tables')).toBeNull())
        expect(screen.getByTestId('ws-nav-design')).toBeInTheDocument()
        // 设计模块不承载质量检查入口（2026-11-02 用户口径）
        expect(screen.queryByRole('tab', { name: /质量检查/ })).toBeNull()
        expect(screen.getByTestId('design-tab-structure')).toHaveAttribute('aria-selected', 'true')
    })

    it('仅勾选文档的工作区访问数据表/数据分析路径自动重定向到文档页', async () => {
        useWorkspaceModules(['documents'])
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        expect(screen.queryByTestId('tables-page-stub')).toBeNull()
    })
})

// ─────────────── 工作区切换：顶部一级导航跳到对应工作区内容（需求 0081 C4） ───────────────

describe('MainLayout 工作区切换', () => {
    it('在文档模块切换工作区：落到目标工作区的文档内容（保持一级导航），而非其落地段', async () => {
        useSwitchTarget(['tables', 'documents'])
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        await switchToTargetWorkspace()

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/20/documents')
        })
        expect(screen.getByTestId('ws-nav-documents')).toHaveAttribute('aria-current', 'page')
    })

    it('在表级子页切换工作区：收敛到目标工作区的数据表模块根，不带上旧表 id', async () => {
        useSwitchTarget(['tables', 'documents'])
        renderLayout(mockUser, '/w/10/tables/100/settings')

        await waitFor(() => {
            expect(screen.getByTestId('table-settings-stub')).toHaveTextContent('/w/10/tables/100/settings')
        })
        await switchToTargetWorkspace()

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        expect(screen.getByTestId('ws-nav-tables')).toHaveAttribute('aria-current', 'page')
    })

    it('二级派生段（数据分析）切换工作区：折算为数据表模块，落到 /tables', async () => {
        useSwitchTarget(['tables'])
        renderLayout(mockUser, '/w/10/analytics')

        await waitFor(() => {
            expect(screen.getByTestId('ws-section-stub')).toHaveTextContent('/w/10/analytics')
        })
        await switchToTargetWorkspace()

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
    })

    it('工作区设置段切换工作区：停留目标工作区的设置页', async () => {
        useSwitchTarget(['design'])
        renderLayout(mockUser, '/w/10/settings')

        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        await switchToTargetWorkspace()

        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/20/settings')
        })
    })

    it('目标工作区未开放当前模块时，落到它有的第一个一级模块默认页', async () => {
        useSwitchTarget(['design'])
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents')
        })
        await switchToTargetWorkspace()

        await waitFor(() => {
            expect(screen.getByTestId('designs-page-stub')).toHaveTextContent('/w/20/design')
        })
        expect(screen.getByTestId('ws-nav-design')).toHaveAttribute('aria-current', 'page')
    })

    it('未开放当前模块且目标有多个模块时，按 数据表 → 文档 → 设计 取第一个可用模块', async () => {
        useSwitchTarget(['tables', 'documents'])
        renderLayout(mockUser, '/w/10/design')

        await waitFor(() => {
            expect(screen.getByTestId('designs-page-stub')).toHaveTextContent('/w/10/design')
        })
        await switchToTargetWorkspace()

        await waitFor(() => {
            expect(screen.getByTestId('tables-page-stub')).toBeVisible()
        })
        expect(screen.getByTestId('ws-nav-tables')).toHaveAttribute('aria-current', 'page')
    })
})

// ─────────────── 侧边栏随功能段切换（需求 0065） ───────────────

describe('MainLayout 侧边栏随功能段切换（需求 0065）', () => {
    it('文档列表页：侧栏显示文档/文件夹树（与文档管理页同源），不再渲染数据表列表', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        // 数据表导航在文档段不渲染
        expect(screen.queryByTestId('sider-tables')).toBeNull()
        // 树同时含文件夹与文档（msw：产品文档 > 需求说明 + 会议纪要）
        await waitFor(() => expect(screen.getByTitle('产品文档')).toBeVisible())
        await waitFor(() => expect(screen.getByTitle('需求说明')).toBeVisible())
        await waitFor(() => expect(screen.getByTitle('会议纪要')).toBeVisible())
    })

    it('未发布锁只标文档不标文件夹：文件夹自身状态恒为草稿，不渲染可见性锁', async () => {
        // 回归：文件夹与文档共用 Document 模型，status 默认 draft → visibility=private；
        // 发布子文档不会发布文件夹，锁若不排除文件夹会对已全发布的文件夹误报「未发布」
        server.use(
            http.get('/api/v1/workspaces/:wid/documents/tree', () =>
                HttpResponse.json({
                    items: [
                        { ...mockDocuments[0], visibility: 'private' }, // 文件夹（draft）
                        { ...mockDocuments[1], visibility: 'private' }, // 文档（draft）
                    ],
                }),
            ),
        )
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        // 私有文档显示锁；文件夹不显示
        await waitFor(() => expect(screen.getByTestId('doc-visibility-2')).toBeVisible())
        expect(screen.queryByTestId('doc-visibility-1')).toBeNull()
    })

    it('长标题节点单行省略：文本截断、完整标题入 title 提示、尾缀图标不参与截断', async () => {
        renderLayout(mockUser, '/w/10/documents')

        // 结构锁定（样式见 index.css .cn-doc-sider-tree）：外层 flex 行 + 内层文本省略
        const node = await screen.findByTitle('需求说明')
        expect(node).toHaveClass('cn-doc-sider-title')
        const text = node.querySelector('.cn-doc-sider-title-text')
        expect(text).toHaveTextContent('需求说明')
    })

    it('点击侧栏文档项导航到对应文档编辑器', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTitle('需求说明')).toBeVisible())
        fireEvent.click(screen.getByTitle('需求说明'))
        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('/w/10/documents/2')
        })
    })

    it('点击侧栏文件夹项导航到对应层级管理页（?parent=）', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTitle('会议纪要')).toBeVisible())
        fireEvent.click(screen.getByTitle('会议纪要'))
        await waitFor(() => {
            expect(screen.getByTestId('documents-page-stub')).toHaveTextContent('parent=3')
        })
    })

    it('侧栏承载展开/收起 / 树排序 / 标题过滤控件（需求 0065 三次修订）', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('doc-tree-expand-toggle')).toBeVisible())
        expect(screen.getByTestId('doc-tree-sort')).toBeVisible()
        expect(screen.getByTestId('doc-tree-filter')).toBeVisible()
        // 刷新按钮已从侧栏移除（刷新走文档页工具栏）
        expect(screen.queryByTestId('doc-sidebar-refresh')).toBeNull()
        // 「手动顺序」文字排序下拉已移除；标签 / 状态筛选在内容区顶部，侧栏不再渲染
        expect(screen.queryByTestId('doc-order-select')).toBeNull()
        expect(screen.queryByTestId('doc-tag-filter')).toBeNull()
        expect(screen.queryByTestId('doc-status-filter')).toBeNull()

        // 树排序下拉可选（与内容区共享偏好，不写 URL）
        fireEvent.click(screen.getByTestId('doc-tree-sort'))
        expect(await screen.findByText('名称 A → Z')).toBeInTheDocument()
    })

    it('展开/收起按钮置于排序之前，点击切换图标与展开态', async () => {
        renderLayout(mockUser, '/w/10/documents')

        const toggle = await screen.findByTestId('doc-tree-expand-toggle')
        const sortBtn = screen.getByTestId('doc-tree-sort')
        // DOM 顺序：展开/收起在排序之前
        expect(sortBtn.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
        // 默认展开态：显示收起图标
        expect(toggle.querySelector('.anticon-menu-fold')).not.toBeNull()
        fireEvent.click(toggle)
        // 收起态：显示展开图标
        await waitFor(() => expect(toggle.querySelector('.anticon-menu-unfold')).not.toBeNull())
    })

    it('主侧栏折叠态本地记忆：刷新恢复收起，展开后写回偏好', async () => {
        localStorage.setItem('cndb_sider_collapsed', 'true')
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => expect(screen.getByTestId('sider-tables')).toBeVisible())
        const sider = document.querySelector('.ant-layout-sider')
        expect(sider).toHaveClass('ant-layout-sider-collapsed')

        const trigger = document.querySelector('.ant-layout-sider-trigger') as HTMLElement
        fireEvent.click(trigger)
        await waitFor(() => expect(localStorage.getItem('cndb_sider_collapsed')).toBe('false'))
    })

    it('文档树展开态会话记忆：刷新后保持收起，点击展开写回会话', async () => {
        sessionStorage.setItem(
            'cndb_doc_tree_state_v1:10',
            JSON.stringify({ expanded: [], collapsedAll: true }),
        )
        renderLayout(mockUser, '/w/10/documents')

        const toggle = await screen.findByTestId('doc-tree-expand-toggle')
        expect(toggle.querySelector('.anticon-menu-unfold')).not.toBeNull()

        fireEvent.click(toggle)
        await waitFor(() => {
            const stored = JSON.parse(sessionStorage.getItem('cndb_doc_tree_state_v1:10') ?? '{}')
            expect(stored.collapsedAll).toBe(false)
        })
    })

    it('工作区设置页：侧栏显示设置分项，不再沿用最近模块侧栏', async () => {
        sessionStorage.setItem('cndb_last_module_sider', '"documents"')
        renderLayout(mockUser, '/w/10/settings')

        await waitFor(() => expect(screen.getByTestId('sider-settings')).toBeVisible())
        expect(screen.getByText('常规设置')).toBeVisible()
        expect(screen.queryByTestId('sider-documents')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('侧栏表搜索词按工作区会话记忆：刷新后仍保留', async () => {
        sessionStorage.setItem('cndb_table_keyword:10', '"客户"')
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => expect(screen.getByTestId('sider-tables')).toBeVisible())
        expect(screen.getByPlaceholderText('搜索表…')).toHaveValue('客户')
    })

    it('文档编辑器段：侧栏仍是同一棵文档树并高亮当前文档，不再显示大纲', async () => {
        renderLayout(mockUser, '/w/10/documents/2')

        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        // 树数据异步返回，标题出现后再断言高亮
        await waitFor(() => expect(screen.getByTitle('需求说明')).toBeVisible())
        // 当前文档高亮
        expect(screen.getByTitle('需求说明').closest('.ant-tree-treenode')).toHaveClass('ant-tree-treenode-selected')
        // 侧栏不再有大纲形态
        expect(screen.queryByTestId('sider-doc-outline')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('工作区设置段：侧栏保持展开并显示设置分项', async () => {
        renderLayout(mockUser, '/w/10/settings')

        await waitFor(() => expect(screen.getByTestId('settings-page-stub')).toBeVisible())
        // 2026-11-02 用户口径：进入工作区设置不再自动折叠侧栏
        const sider = document.querySelector('.ant-layout-sider')
        expect(sider).not.toBeNull()
        expect(sider).not.toHaveClass('ant-layout-sider-collapsed')
        // 侧栏内容为设置分项，不再显示数据表导航
        expect(screen.getByTestId('sider-settings')).toBeVisible()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it.each(['/w/10/analytics', '/w/10/datasource', '/w/10/pipelines'])(
        '分析 / 同步 / 质量检查段：数据表侧栏始终展开不折叠（%s）', async (path) => {
            renderLayout(mockUser, path)

            await waitFor(() => expect(screen.getByTestId('ws-section-stub')).toBeVisible())
            const sider = document.querySelector('.ant-layout-sider')
            expect(sider).not.toBeNull()
            expect(sider).not.toHaveClass('ant-layout-sider-collapsed')
            expect(screen.getByTestId('sider-tables')).toBeVisible()
        })

    it('数据表段维持表导航：数据表列表侧栏不受文档段切换影响', async () => {
        renderLayout(mockUser, '/w/10/tables')

        await waitFor(() => expect(screen.getByTestId('sider-tables')).toBeVisible())
        expect(screen.queryByTestId('sider-documents')).toBeNull()
        expect(screen.queryByTestId('sider-doc-outline')).toBeNull()
    })

    it('移动端文档段：抽屉导航显示文档树而非表列表', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        renderLayout(mockUser, '/w/10/documents')

        fireEvent.click(screen.getByTestId('mobile-nav-btn'))
        expect(await screen.findByTestId('sider-documents')).toBeVisible()
        expect(screen.queryByText('数据表 (')).toBeNull()

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })
})

// ─────────────── 设计段侧栏（ADR 0084 D4 / D5） ───────────────

/** 设计列表 fixture：侧栏装配树的根节点（大纲按设计懒加载） */
const mockDesignList = [
    {
        id: 20,
        workspace_id: 10,
        title: '四轮小车',
        description: '三级装配示例',
        version_count: 2,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
    },
]

/** 装配大纲 fixture：系统 → 组件 → 零件 + 系统直属零件（ADR 0084 §9） */
const mockDesignOutline = {
    design_id: 20,
    version_number: 2,
    source: 'compiled' as const,
    outline: {
        children: [{
            kind: 'system',
            name: 'rover',
            line: 27,
            col: 1,
            children: [
                {
                    kind: 'assembly',
                    name: 'chassis',
                    line: 28,
                    col: 3,
                    children: [{ kind: 'part', primitive: 'box', line: 22, col: 5 }],
                },
                { kind: 'part', primitive: 'sphere', line: 34, col: 3 },
            ],
        }],
    },
}

function useDesignSidebar() {
    server.use(
        http.get('/api/v1/workspaces/:wid/designs', () => HttpResponse.json(mockDesignList)),
        http.get('/api/v1/workspaces/:wid/designs/:designId/outline', () => HttpResponse.json(mockDesignOutline)),
    )
}

/** 点击树节点展开箭头（antd 展开动画窗口约 600ms 会吞下一次点击，先等待） */
async function expandDesignNode(testId: string) {
    await new Promise(resolve => setTimeout(resolve, 600))
    const switcher = screen.getByTestId(testId)
        .closest('.ant-tree-treenode')
        ?.querySelector('.ant-tree-switcher')
    expect(switcher).toBeTruthy()
    fireEvent.click(switcher as Element)
    await waitFor(() => {
        expect(screen.getByTestId(testId).closest('.ant-tree-treenode')?.getAttribute('aria-expanded')).toBe('true')
    })
}

describe('MainLayout 工作区设置段侧栏（2026-11-08 用户口径）', () => {
    it('从文档模块进入工作区设置：侧栏切换为设置分项，不再保留文档树', async () => {
        renderLayout(mockUser, '/w/10/documents')

        await waitFor(() => expect(screen.getByTestId('sider-documents')).toBeVisible())
        fireEvent.click(screen.getByTestId('ws-nav-settings'))
        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        expect(screen.getByTestId('sider-settings')).toBeVisible()
        expect(screen.queryByTestId('sider-documents')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('从设计编辑器进入工作区设置：侧栏切换为设置分项，不再保留装配结构树', async () => {
        useDesignSidebar()
        renderLayout(mockUser, '/w/10/design/20')

        await waitFor(() => expect(screen.getByTestId('sider-designs')).toBeVisible())
        fireEvent.click(screen.getByTestId('ws-nav-settings'))
        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        expect(screen.getByTestId('sider-settings')).toBeVisible()
        expect(screen.queryByTestId('sider-designs')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('直接打开工作区设置：侧栏显示设置分项', async () => {
        renderLayout(mockUser, '/w/10/settings')

        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings')
        })
        expect(screen.getByTestId('sider-settings')).toBeVisible()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('点击侧栏分项：写入 ?section= 并同步选中态', async () => {
        renderLayout(mockUser, '/w/10/settings')

        await waitFor(() => expect(screen.getByTestId('sider-settings')).toBeVisible())
        fireEvent.click(screen.getByText('权限管理'))

        await waitFor(() => {
            expect(screen.getByTestId('settings-page-stub')).toHaveTextContent('/w/10/settings?section=permissions')
        })
        const selected = screen.getByTestId('sider-settings').querySelector('.ant-menu-item-selected')
        expect(selected).toHaveTextContent('权限管理')
    })
})

describe('MainLayout 设计段侧栏（ADR 0084 / 0109 D4 / D8）', () => {
    it('设计根页同样渲染侧栏，且为产品列表态', async () => {
        useDesignSidebar()
        renderLayout(mockUser, '/w/10/design')

        await waitFor(() => expect(screen.getByTestId('designs-page-stub')).toBeVisible())
        // 根页与编辑器共用同一侧栏（D8）：根页落在产品列表态（D4）
        expect(await screen.findByTestId('sider-designs')).toBeVisible()
        expect(await screen.findByTestId('design-products-panel')).toBeVisible()
        expect(await screen.findByTestId('design-row-20')).toBeVisible()
        expect(screen.queryByTestId('design-outline-panel')).toBeNull()
        expect(screen.queryByTestId('sider-tables')).toBeNull()
        expect(screen.queryByTestId('sider-documents')).toBeNull()
    })

    it('设计编辑器页：自动展开当前设计并加载大纲，选中态高亮', async () => {
        useDesignSidebar()
        renderLayout(mockUser, '/w/10/design/20')

        // 进入编辑器即见装配结构（C1）：设计根自动展开并加载系统级节点
        await waitFor(() => expect(screen.getByTestId('design-outline-node-design-20-0')).toBeVisible())
        expect(screen.getByTestId('design-outline-node-design-20-0')).toHaveTextContent('rover')
        expect(screen.getByTestId('design-outline-node-design-20-0')).toHaveTextContent('系统 · 第 27 行 · 2 个零件')
        // 当前设计高亮（侧栏树 selectedKeys 由编辑器路由驱动）
        expect(screen.getByTestId('design-node-20').closest('.ant-tree-treenode'))
            .toHaveClass('ant-tree-treenode-selected')
        expect(screen.queryByTestId('sider-tables')).toBeNull()
    })

    it('展开系统后点击零件节点定位编辑器源行（?line=）', async () => {
        useDesignSidebar()
        renderLayout(mockUser, '/w/10/design/20')

        await waitFor(() => expect(screen.getByTestId('design-outline-node-design-20-0')).toBeVisible())
        await expandDesignNode('design-outline-node-design-20-0')
        fireEvent.click(await screen.findByText('球体'))
        await waitFor(() => {
            expect(screen.getByTestId('designs-page-stub')).toHaveTextContent('/w/10/design/20?line=34')
        })
    })

    it('移动端设计段：抽屉导航显示装配结构而非表列表，点击节点后收起', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        useDesignSidebar()
        renderLayout(mockUser, '/w/10/design/20')

        fireEvent.click(screen.getByTestId('mobile-nav-btn'))
        await waitFor(() => expect(screen.getByTestId('sider-designs')).toBeVisible())
        expect(screen.queryByText('数据表 (')).toBeNull()

        // 展开系统 → 点击零件 → 导航并自动收起抽屉
        await waitFor(() => expect(screen.getByTestId('design-outline-node-design-20-0')).toBeVisible())
        await expandDesignNode('design-outline-node-design-20-0')
        fireEvent.click(await screen.findByText('球体'))
        await waitFor(() => expect(document.querySelector('.ant-drawer-open')).toBeNull())

        responsiveState = {
            deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
            width: 1280, height: 800,
        }
    })
})

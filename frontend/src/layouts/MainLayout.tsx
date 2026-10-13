import React, { Suspense, lazy, useState, useCallback } from 'react'
import { Outlet, useNavigate, useParams, useSearchParams, useLocation, Navigate } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Button, Space, App as AntApp, Input, Tooltip, Tabs, Drawer } from 'antd'
import type { MenuProps, TabsProps } from 'antd'
import {
  LogoutOutlined, AppstoreOutlined, TableOutlined,
  UserOutlined, ExclamationCircleOutlined, SearchOutlined,
  SettingOutlined, SafetyOutlined, QuestionCircleOutlined,
  MenuOutlined, InfoCircleOutlined,
  DatabaseOutlined, BarChartOutlined,
  PullRequestOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { tableApi, workspaceApi } from '@/api'
import { useAuthStore, useUiStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'

// Modal 组件 lazy import：点击打开时才加载
const SettingsModal = lazy(() => import('@/pages/settings/SettingsModal'))
// 帮助中心抽屉 lazy import：点击打开时才加载
const HelpCenterDrawer = lazy(() => import('@/components/HelpCenterDrawer'))
// 关于系统弹窗 lazy import：点击打开时才加载
const AboutModal = lazy(() => import('@/components/AboutModal'))
// 新手引导：MainLayout 挂载一次，内部自行判定触发时机
const OnboardingTour = lazy(() => import('@/components/onboarding/OnboardingTour'))

function ModalFallback() {
  return null
}

/** 表级子页定义 —— 融合导航行面包屑的下拉菜单与当前位置展示共用；顺序即菜单顺序. */
const TABLE_SUBPAGES = [
  { key: 'change-requests', label: '修改申请', icon: <PullRequestOutlined /> },
  { key: 'issues', label: '问题清单', icon: <ExclamationCircleOutlined /> },
  { key: 'settings', label: '数据表设置', icon: <SettingOutlined /> },
] as const

/** 内容区骨架 —— 懒加载页面在 Content 内挂起时的占位，避免整页高度跳动 */
function ContentFallback() {
  return (
    <div style={{ padding: 24 }} aria-label="页面加载中">
      <div style={{ height: 28, width: 220, borderRadius: 6, background: 'var(--cn-border)', marginBottom: 16 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{ height: 40, borderRadius: 8, background: 'var(--cn-border)', opacity: 0.5 }} />
        ))}
      </div>
    </div>
  )
}

const { Header, Sider, Content } = Layout

export default function MainLayout() {
  const navigate = useNavigate()
  const { modal } = AntApp.useApp()
  const { wid, tid } = useParams<{ wid: string; tid?: string }>()
  const location = useLocation().pathname
  const user = useAuthStore(s => s.user)
  const logout = useAuthStore(s => s.logout)
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const settingsOpen = useUiStore(s => s.settingsOpen)
  const settingsTab = useUiStore(s => s.settingsTab)
  const openSettings = useUiStore(s => s.openSettings)
  const closeSettings = useUiStore(s => s.closeSettings)
  const [helpOpen, setHelpOpen] = useState(false)
  // 关于系统弹窗开关 —— 所有登录用户可见
  const [aboutOpen, setAboutOpen] = useState(false)
  const [searchParams] = useSearchParams()
  // 移动端抽屉导航开关（仅 isMobile 时渲染汉堡入口）
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  /** 跨表导航时保留当前 URL 的 query params（如 ?mode=calendar、?view=123）. */
  const navigateToTable = useCallback((targetWid: string | number, targetTid: string | number) => {
    const params = new URLSearchParams()
    // 复制需要保留的 params
    for (const key of ['mode', 'view']) {
      const v = searchParams.get(key)
      if (v) params.set(key, v)
    }
    const qs = params.toString()
    navigate(`/w/${targetWid}/tables/${targetTid}${qs ? `?${qs}` : ''}`)
  }, [searchParams, navigate])

  /** hover 预取表详情 —— 点击进表时 useTable 命中缓存，减少冷启动白屏（queryKey 与 useTable 一致）. */
  const prefetchTable = useCallback((targetWid: string, targetTid: string | number) => {
    void queryClient.prefetchQuery({
      queryKey: ['table', `${targetWid}/${targetTid}`],
      queryFn: () => tableApi.get(targetWid, String(targetTid)),
      staleTime: 60_000,
    })
  }, [queryClient])

  const { data: workspaces = [], isLoading: wsLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  const { data: tables = [], isSuccess: tablesReady } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => (wid ? tableApi.list(wid) : Promise.resolve([])),
    enabled: !!wid,
  })

  // 后端已按 DataTable.order（用户拖拽顺序）返回，这里直接使用即可。
  const orderedTables = tables

  const currentWs = workspaces.find(w => String(w.id) === wid)

  /** 工作区级分页导航：key 即路由段（/w/:wid/{key}），覆盖数据表、表单、报表与设置入口.
   *
   * 各项带数量徽标：仅数据就绪后渲染徽标（0 也显示），未就绪时不渲染占位，
   * 避免加载瞬间误导（class cn-ws-tab-count，样式走 var(--cn-*) 主题变量）。
   * 「工作区设置」无徽标。
   */
  const wsTabItems: TabsProps['items'] = [
    {
      key: 'tables',
      label: (
        <span>
          <DatabaseOutlined /> 数据表
          {tablesReady && <span className="cn-ws-tab-count">{tables.length}</span>}
        </span>
      ),
    },
    {
      key: 'forms',
      label: (
        <span>
          <DatabaseOutlined /> 表单
        </span>
      ),
    },
    {
      key: 'reports',
      label: (
        <span>
          <BarChartOutlined /> 报表
          {currentWs && currentWs.report_count !== undefined && (
            <span className="cn-ws-tab-count">{currentWs.report_count}</span>
          )}
        </span>
      ),
    },
    { key: 'settings', label: <span><SettingOutlined /> 工作区设置</span> },
  ]
  // ── 表级页签（融合导航行，紧随工作区分页之后）──
  // 当 URL 处于某张表的上下文（网格页 /w/:wid/tables/:tid 及其子页）时，
  // 在工作区 Tabs 右侧以竖线分割后渲染：表名（点击返回网格）+ 子页页签（GitHub 风格页签切换）。
  const inTableContext = !!wid && !!tid && location.startsWith(`/w/${wid}/tables/${tid}`)
  const currentTable = orderedTables.find(t => String(t.id) === String(tid))
  const activeTableTab = location.includes('/change-requests')
    ? 'change-requests'
    : location.includes('/issues')
      ? 'issues'
      : location.includes('/settings')
        ? 'settings'
        : ''
  const activeSubpage = TABLE_SUBPAGES.find(p => p.key === activeTableTab)

  // 激活态由 pathname 驱动：表详情页及表级子页一律落在「数据表」（子页高亮由表级导航负责），
  // 避免表设置页（/tables/:tid/settings）被误判为「工作区设置」
  const activeWsTab = inTableContext
    ? 'tables'
    : location.includes('/forms')
      ? 'forms'
      : location.includes('/reports')
        ? 'reports'
        : location.includes('/settings')
          ? 'settings'
          : 'tables'

  const isAdmin = !!user && (user.is_superuser || user.role === 'system_admin')

  const onLogout = useCallback(() => {
    modal.confirm({
      title: '退出登录？',
      icon: React.createElement(ExclamationCircleOutlined),
      onOk: () => {
        logout()
        queryClient.clear()
        navigate('/login', { replace: true })
      },
    })
  }, [logout, navigate, queryClient, modal])

  const workspaceMenuItems: MenuProps['items'] = [
    { type: 'group', label: '工作区' },
    ...workspaces.map(w => ({
      key: `ws-${w.id}`,
      icon: <AppstoreOutlined />,
      label: (w.pinned ? '📌 ' : '') + w.name,
      onClick: () => navigate(`/w/${w.id}/tables`),
    })),
  ]

  const userMenuItems: MenuProps['items'] = [
    { key: 'user', icon: <UserOutlined />, label: user?.username || '用户', disabled: true },
    { type: 'divider' },
    { key: 'settings', icon: <SettingOutlined />, label: '个人设置', onClick: () => openSettings() },
    // 关于系统：普通用户与管理员均可见，查看版本等基本信息
    { key: 'about', icon: <InfoCircleOutlined />, label: '关于系统', onClick: () => setAboutOpen(true) },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout },
  ]

  if (!wid) {
    if (wsLoading) {
      return React.createElement('div', { style: { padding: 48, textAlign: 'center' } }, '加载中...')
    }
    // 访问 / 时，让 index route 的 <Navigate to="/w" /> 生效；访问 /w 时让 Outlet 渲染 WorkspaceList.
    // 两种情况都必须返回 <Outlet /> 所在的布局，否则子路由（包括 Navigate）根本不会挂载。
    // 无 wid 的合法路径（/、/w、/admin 等）正常渲染布局；仅对需要 wid 的 /w/... 路径重定向
    if (!location.startsWith('/w/')) {
      // 正常落到下方 return 的布局 —— Outlet 渲染子路由
    } else if (workspaces.length > 0) {
      // 访问了需要 wid 的 URL 但没带 wid → 跳到第一个工作区
      const first = workspaces[0]
      return <Navigate to={`/w/${first.id}/tables`} replace />
    } else {
      // 空工作区 + 需要 wid 的 URL（不是 / 也不是 /w）→ 跳到 /w 让用户创建
      return <Navigate to="/w" replace />
    }
  }

  /** 表导航内容 —— 桌面端 Sider 与移动端抽屉共用；mobile=true 时点击表项后自动收起抽屉.
   * collapsed 仅桌面端 Sider 折叠态使用，与既有折叠隐藏逻辑保持一致。 */
  const renderTableNav = (mobile: boolean, collapsed = false) => {
    if (!wid) {
      // 未进入工作区：不渲染"数据表"导航，提示用户从顶部选择
      return (
        <div data-testid="sider-no-workspace" style={{
          padding: '24px 16px', textAlign: 'center', color: 'var(--cn-text-muted)', fontSize: 13,
          display: collapsed ? 'none' : 'block',
        }}>
          <p style={{ margin: 0 }}>请先从顶部选择一个工作区</p>
        </div>
      )
    }
    return (
      <div data-testid="sider-tables" className="cn-table-nav">
        <div style={{
          padding: '12px 16px', borderBottom: '1px solid var(--cn-border)',
          display: collapsed ? 'none' : 'flex', alignItems: 'center', gap: 8,
        }}>
          <Input prefix={<SearchOutlined />} placeholder="搜索表..." allowClear />
        </div>
        <div style={{ padding: '8px 16px', fontWeight: 600, color: 'var(--cn-text-secondary)', fontSize: 12, display: collapsed ? 'none' : 'block' }}>
          数据表 ({orderedTables.length})
        </div>
        {tables.length === 0 ? (
          collapsed ? (
            <div style={{ padding: 16, textAlign: 'center', color: 'var(--cn-text-muted)', fontSize: 13 }}>无表</div>
          ) : (
            <div style={{ padding: '20px 16px', textAlign: 'center', color: 'var(--cn-text-muted)', fontSize: 13 }}>
              <p style={{ margin: 0 }}>还没有数据表，先创建或导入一张吧</p>
            </div>
          )
        ) : (
          <Menu
            mode="inline"
            selectedKeys={tid ? [String(tid)] : []}
            items={orderedTables.map(t => ({
              key: String(t.id),
              icon: <TableOutlined />,
              label: <span onMouseEnter={() => prefetchTable(wid!, t.id)}>{t.name}</span>,
              onClick: () => {
                navigateToTable(wid!, t.id)
                if (mobile) setMobileNavOpen(false)
              },
            }))}
          />
        )}
      </div>
    )
  }

  return (
    <Layout style={{ height: '100vh', minHeight: 0 }}>
      <Header className="cn-app-header" style={{
        padding: '0 16px', height: 52, lineHeight: '52px', flexShrink: 0,
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        {/* 移动端汉堡入口：替代常驻 Sider，点击打开抽屉导航 */}
        {isMobile && (
          <Button
            type="text"
            icon={<MenuOutlined />}
            aria-label="打开导航菜单"
            data-testid="mobile-nav-btn"
            onClick={() => setMobileNavOpen(true)}
          />
        )}
        <Tooltip title="主页">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginRight: 8, cursor: 'pointer' }}
            data-testid="home-logo"
            onClick={() => navigate('/w')}>
            <span
              className="cn-brand-mark"
              style={{ width: 26, height: 26, fontSize: 14, borderRadius: 7 }}
              aria-hidden
            >
              c
            </span>
            {!isMobile && (
              <span style={{ fontWeight: 700, fontSize: 16, color: 'var(--cn-text-primary)', letterSpacing: '-0.2px' }}>
                cndb
              </span>
            )}
          </div>
        </Tooltip>

        {/* 工作区下拉 —— 移动端仅显示图标，节省横向空间 */}
        <Dropdown menu={{ items: workspaceMenuItems }} trigger={['click']}>
          <Button type="text" icon={<AppstoreOutlined />} data-testid="ws-switch-btn">
            {!isMobile && (currentWs?.name || '工作区')}
          </Button>
        </Dropdown>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
          {/* 帮助中心入口 —— 所有登录用户可见 */}
          <Tooltip title="帮助中心与新手引导">
            <Button
              type="text"
              size="small"
              icon={<QuestionCircleOutlined />}
              data-testid="help-btn"
              onClick={() => setHelpOpen(true)}
            >{!isMobile && '帮助'}</Button>
          </Tooltip>
          {/* 系统管理台入口 —— 仅管理员可见，置于用户头像左侧以区别于常规导航 */}
          {isAdmin && (
            <Tooltip title="系统管理台">
              <Button
                type={location.includes('/admin') ? 'primary' : 'text'}
                size="small" icon={<SafetyOutlined />}
                onClick={() => navigate('/admin')}
              >{!isMobile && '管理台'}</Button>
            </Tooltip>
          )}
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              {/* 右上角优先展示昵称，无昵称时回退账号名 */}
              {!isMobile && <span>{user?.nickname || user?.username || ''}</span>}
            </Space>
          </Dropdown>
        </div>
      </Header>

      <Layout style={{ flex: 1, minHeight: 0 }}>
        {/* 移动端不渲染常驻 Sider，改用下方抽屉导航；桌面端行为不变 */}
        {!isMobile && (
          <Sider
            collapsible collapsed={collapsed} onCollapse={setCollapsed}
            width={240} collapsedWidth={60}
            style={{ background: 'var(--cn-bg-container)', borderRight: '1px solid var(--cn-border)', flexShrink: 0, overflow: 'auto' }}
          >
            {renderTableNav(false, collapsed)}
          </Sider>
        )}

        <Layout style={{ flex: 1, minHeight: 0 }}>
          {/* 工作区级分页导航 —— 位于 Content 之外，跨页切换不重挂载；无工作区上下文时不渲染。
              表上下文时紧随其后以竖线分割出表级页签段：表名回网格 + 子页页签切换（GitHub 风格） */}
          {wid && (
            <div className="cn-ws-tabs" style={{
              background: 'var(--cn-bg-container)', borderBottom: '1px solid var(--cn-border)', flexShrink: 0,
              display: 'flex', alignItems: 'stretch', overflowX: 'auto',
            }}>
              <Tabs
                activeKey={activeWsTab}
                items={wsTabItems}
                style={{ flex: '0 1 auto', minWidth: 0 }}
                tabBarStyle={{ margin: 0, padding: '0 16px' }}
                onChange={(key) => navigate(`/w/${wid}/${key}`)}
              />
              {inTableContext && (
                <div className="cn-table-crumb" data-testid="table-crumb">
                  <span className="cn-table-crumb-divider" aria-hidden />
                  <Button
                    type="text"
                    size="small"
                    data-testid="table-crumb-table"
                    style={{ paddingInline: 8 }}
                    onClick={() => navigate(`/w/${wid}/tables/${tid}`)}
                  >
                    <span className="cn-table-crumb-name">{currentTable?.name || '数据表'}</span>
                  </Button>
                  {/* 表级子页页签 —— 激活态与选中项由 pathname 驱动，替代旧的 ▾ 下拉切换 */}
                  <nav className="cn-table-tabs" aria-label="表级页面切换">
                    {TABLE_SUBPAGES.map(p => {
                      const active = activeSubpage?.key === p.key
                      return (
                        <button
                          key={p.key}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          data-testid={`table-tab-${p.key}`}
                          className={active ? 'cn-table-tab cn-table-tab-active' : 'cn-table-tab'}
                          onClick={() => navigate(`/w/${wid}/tables/${tid}/${p.key}`)}
                        >
                          {p.icon}
                          {p.label}
                        </button>
                      )
                    })}
                  </nav>
                </div>
              )}
            </div>
          )}
          <Content
            key={location}
            className="cn-page-enter"
            style={{ background: 'var(--cn-bg-page)', flex: 1, minHeight: 0, overflow: 'auto' }}
          >
            {/* 懒加载页面在 Content 内挂起 —— MainLayout 保持挂载，仅内容区显示骨架，整页不再跳动 */}
            <Suspense fallback={<ContentFallback />}>
              <Outlet />
            </Suspense>
          </Content>
        </Layout>
      </Layout>

      {/* 移动端抽屉导航：替代常驻 Sider，点击表项后自动收起 */}
      <Drawer
        title="导航"
        placement="left"
        open={isMobile && mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        width={280}
        styles={{ body: { padding: 0 } }}
      >
        {renderTableNav(true)}
      </Drawer>

      <Suspense fallback={<ModalFallback />}>
        <SettingsModal open={settingsOpen} initialTab={settingsTab} onClose={closeSettings} />
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        {helpOpen && <HelpCenterDrawer open onClose={() => setHelpOpen(false)} />}
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} />
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        <OnboardingTour />
      </Suspense>
    </Layout>
  )
}

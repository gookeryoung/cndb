import React, { Suspense, lazy, useState, useCallback } from 'react'
import { Outlet, useNavigate, useParams, useSearchParams, useLocation, Navigate } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Button, Space, Modal, Input, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  LogoutOutlined, AppstoreOutlined, TableOutlined,
  FileTextOutlined,
  UserOutlined, ExclamationCircleOutlined, SearchOutlined,
  SettingOutlined, SafetyOutlined, QuestionCircleOutlined, PlusOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { workspaceApi, tableApi } from '@/api'
import { useAuthStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'

// Modal 组件 lazy import：点击打开时才加载
const SettingsModal = lazy(() => import('@/pages/modals/SettingsModal'))
// 帮助中心抽屉 lazy import：点击打开时才加载
const HelpCenterDrawer = lazy(() => import('@/components/HelpCenterDrawer'))
// 新手引导：MainLayout 挂载一次，内部自行判定触发时机
const OnboardingTour = lazy(() => import('@/components/onboarding/OnboardingTour'))

function ModalFallback() {
  return null
}

const { Header, Sider, Content } = Layout

export default function MainLayout() {
  const navigate = useNavigate()
  const { wid, tid } = useParams<{ wid: string; tid?: string }>()
  const location = useLocation().pathname
  const user = useAuthStore(s => s.user)
  const logout = useAuthStore(s => s.logout)
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [searchParams] = useSearchParams()

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

  const { data: workspaces = [], isLoading: wsLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  const { data: tables = [] } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => (wid ? tableApi.list(wid) : Promise.resolve([])),
    enabled: !!wid,
  })

  // 后端已按 DataTable.order（用户拖拽顺序）返回，这里直接使用即可。
  const orderedTables = tables

  const currentWs = workspaces.find(w => String(w.id) === wid)

  const isAdmin = !!user && (user.is_superuser || user.role === 'system_admin')

  const onLogout = useCallback(() => {
    Modal.confirm({
      title: '退出登录？',
      icon: React.createElement(ExclamationCircleOutlined),
      onOk: () => {
        logout()
        queryClient.clear()
        navigate('/login', { replace: true })
      },
    })
  }, [logout, navigate, queryClient])

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
    { key: 'settings', icon: <SettingOutlined />, label: '个人设置', onClick: () => setSettingsOpen(true) },
    { key: 'help', icon: <QuestionCircleOutlined />, label: '帮助中心', onClick: () => setHelpOpen(true) },
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

  return (
    <Layout style={{ height: '100vh', minHeight: 0 }}>
      <Header style={{
        background: 'var(--cn-bg-container)', padding: '0 16px', height: 52, lineHeight: '52px', flexShrink: 0,
        display: 'flex', alignItems: 'center', gap: 12, borderBottom: '1px solid var(--cn-border)',
      }}>
        <div style={{ fontWeight: 700, fontSize: 18, color: 'var(--cn-brand-color)', marginRight: 8, cursor: 'pointer' }}
          onClick={() => navigate('/w')}>cndb</div>

        {/* 工作区下拉 */}
        <Dropdown menu={{ items: workspaceMenuItems }} trigger={['click']}>
          <Button type="text" icon={<AppstoreOutlined />} data-testid="ws-switch-btn">
            {currentWs?.name || '工作区'}
          </Button>
        </Dropdown>

        {/* Header 常规导航按钮 —— 工作区级功能，显式作用于左侧下拉框当前工作区；无工作区时禁用（管理台在右上角用户区，与常规功能区分） */}
        <Space size={4}>
          <Tooltip title={currentWs ? '报表' : '请先选择工作区'}>
            <span style={{ display: 'inline-flex' }}>
              <Button
                type={location.includes('/reports') ? 'primary' : 'text'}
                size="small" icon={<FileTextOutlined />}
                disabled={!currentWs}
                onClick={() => currentWs && navigate(`/w/${currentWs.id}/reports`)}
              >{!isMobile && '报表'}</Button>
            </span>
          </Tooltip>
          <Tooltip title={currentWs ? '工作区设置' : '请先选择工作区'}>
            <span style={{ display: 'inline-flex' }}>
              <Button
                type={location.includes('/settings') ? 'primary' : 'text'}
                size="small" icon={<SettingOutlined />}
                disabled={!currentWs}
                data-testid="workspace-settings-nav"
                onClick={() => currentWs && navigate(`/w/${currentWs.id}/settings`)}
              >{!isMobile && '工作区设置'}</Button>
            </span>
          </Tooltip>
        </Space>

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
              {!isMobile && <span>{user?.username || ''}</span>}
            </Space>
          </Dropdown>
        </div>
      </Header>

      <Layout style={{ flex: 1, minHeight: 0 }}>
        <Sider
          collapsible collapsed={collapsed} onCollapse={setCollapsed}
          width={240} collapsedWidth={60}
          style={{ background: 'var(--cn-bg-container)', borderRight: '1px solid var(--cn-border)', flexShrink: 0, overflow: 'auto' }}
        >
          <div data-testid="sider-tables">
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
                  <p style={{ marginBottom: 12 }}>还没有数据表，先创建或导入一张吧</p>
                  <Button
                    type="primary"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => navigate(wid ? `/w/${wid}/tables` : '/w')}
                  >新建表</Button>
                </div>
              )
            ) : (
              <Menu
                mode="inline"
                selectedKeys={tid ? [String(tid)] : []}
                items={orderedTables.map(t => ({
                  key: String(t.id),
                  icon: <TableOutlined />,
                  label: t.name,
                  onClick: () => navigateToTable(wid!, t.id),
                }))}
              />
            )}
          </div>
        </Sider>

        <Content style={{ background: 'var(--cn-bg-page)', flex: 1, minHeight: 0, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>

      <Suspense fallback={<ModalFallback />}>
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        {helpOpen && <HelpCenterDrawer open onClose={() => setHelpOpen(false)} />}
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        <OnboardingTour />
      </Suspense>
    </Layout>
  )
}

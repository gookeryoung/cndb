import React, { Suspense, lazy, useState, useCallback } from 'react'
import { Outlet, useNavigate, useParams, useSearchParams, Navigate } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Button, Space, Modal, Input, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  LogoutOutlined, AppstoreOutlined, TableOutlined,
  FileTextOutlined,
  UserOutlined, ExclamationCircleOutlined, SearchOutlined,
  SettingOutlined, SafetyOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { workspaceApi, tableApi } from '@/api'
import { useAuthStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'

// Modal 组件 lazy import：点击打开时才加载
const SettingsModal = lazy(() => import('@/pages/modals/SettingsModal'))

function ModalFallback() {
  return null
}

const { Header, Sider, Content } = Layout

export default function MainLayout() {
  const navigate = useNavigate()
  const { wid, tid } = useParams<{ wid: string; tid?: string }>()
  const location = window.location.pathname
  const user = useAuthStore(s => s.user)
  const logout = useAuthStore(s => s.logout)
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
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
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout },
  ]

  if (!wid) {
    if (wsLoading) {
      return React.createElement('div', { style: { padding: 48, textAlign: 'center' } }, '加载中...')
    }
    // 访问 / 时，让 index route 的 <Navigate to="/w" /> 生效；访问 /w 时让 Outlet 渲染 WorkspaceList.
    // 两种情况都必须返回 <Outlet /> 所在的布局，否则子路由（包括 Navigate）根本不会挂载。
    if (location.endsWith('/w') || location === '/') {
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
          <Button type="text" icon={<AppstoreOutlined />}>
            {currentWs?.name || '工作区'}
          </Button>
        </Dropdown>

        {/* Header 导航按钮 */}
        <Space size={4}>
          {isAdmin && (
            <Tooltip title="系统管理台">
              <Button
                type={location.includes('/admin') ? 'primary' : 'text'}
                size="small" icon={<SafetyOutlined />}
                onClick={() => navigate('/admin')}
              >{!isMobile && '管理台'}</Button>
            </Tooltip>
          )}
          <Button
            type={location.includes('/reports') ? 'primary' : 'text'}
            size="small" icon={<FileTextOutlined />}
            onClick={() => navigate(`/w/${wid}/reports`)}
          >{!isMobile && '报表'}</Button>
          <Tooltip title="工作区设置">
            <Button
              type={location.includes('/settings') ? 'primary' : 'text'}
              size="small" icon={<SettingOutlined />}
              data-testid="workspace-settings-nav"
              onClick={() => navigate(`/w/${wid}/settings`)}
            >{!isMobile && '设置'}</Button>
          </Tooltip>
        </Space>

        <div style={{ marginLeft: 'auto' }}>
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
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--cn-text-muted)', fontSize: 13 }}>
              暂无表
            </div>
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
        </Sider>

        <Content style={{ background: 'var(--cn-bg-page)', flex: 1, minHeight: 0, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>

      <Suspense fallback={<ModalFallback />}>
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </Suspense>
    </Layout>
  )
}

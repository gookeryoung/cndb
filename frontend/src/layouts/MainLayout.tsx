import React, { Suspense, lazy, useMemo, useState, useCallback } from 'react'
import { Outlet, useNavigate, useParams, Navigate } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Button, Space, Modal, Input, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  LogoutOutlined, AppstoreOutlined, TableOutlined,
  NodeIndexOutlined, DeleteOutlined, FileTextOutlined,
  UserOutlined, ExclamationCircleOutlined, SearchOutlined,
  TeamOutlined, SettingOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { workspaceApi, tableApi } from '@/api'
import { useAuth } from '@/auth/AuthContext'
import { useResponsive } from '@/hooks/useResponsive'

// Modal 组件 lazy import：点击打开时才加载
const SettingsModal = lazy(() => import('@/pages/modals/SettingsModal'))
const MembersModal = lazy(() => import('@/pages/modals/MembersModal'))

function ModalFallback() {
  return null
}

const { Header, Sider, Content } = Layout

export default function MainLayout() {
  const navigate = useNavigate()
  const { wid, tid } = useParams<{ wid: string; tid?: string }>()
  const location = window.location.pathname
  const { user, logout } = useAuth()
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)

  const { data: workspaces = [], isLoading: wsLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  const { data: tables = [] } = useQuery({
    queryKey: ['tables', wid],
    queryFn: () => (wid ? tableApi.list(wid) : Promise.resolve([])),
    enabled: !!wid,
  })

  const orderedTables = useMemo(
    () => [...tables].sort((a, b) => (a.name || '').localeCompare(b.name || '')),
    [tables],
  )

  const currentWs = workspaces.find(w => String(w.id) === wid)

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
    { key: 'settings', icon: <SettingOutlined />, label: '个人设置（Token / 主题）', onClick: () => setSettingsOpen(true) },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout },
  ]

  if (!wid) {
    if (wsLoading) {
      return React.createElement('div', { style: { padding: 48, textAlign: 'center' } }, '加载中...')
    }
    if (workspaces.length === 0) {
      return React.createElement('div', { style: { padding: 48, textAlign: 'center' } },
        React.createElement('h2', null, '欢迎使用 cndb'),
        React.createElement('p', { style: { color: '#6b7280' } }, '还没有任何工作区'),
      )
    }
    const first = workspaces[0]
    return <Navigate to={`/w/${first.id}/tables`} replace />
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{
        background: '#fff', padding: '0 16px', height: 52, lineHeight: '52px',
        display: 'flex', alignItems: 'center', gap: 12, borderBottom: '1px solid #e5e7eb',
      }}>
        <div style={{ fontWeight: 700, fontSize: 18, color: '#3b82f6', marginRight: 8, cursor: 'pointer' }}
          onClick={() => navigate('/w')}>cndb</div>

        {/* 工作区下拉 */}
        <Dropdown menu={{ items: workspaceMenuItems }} trigger={['click']}>
          <Button type="text" icon={<AppstoreOutlined />}>
            {currentWs?.name || '工作区'}
          </Button>
        </Dropdown>

        {/* Header 导航按钮 */}
        <Space size={4}>
          <Button
            type={location.includes('/graph') ? 'primary' : 'text'}
            size="small" icon={<NodeIndexOutlined />}
            onClick={() => navigate(`/w/${wid}/graph`)}
          >{!isMobile && '关系图'}</Button>
          <Button
            type={location.includes('/trash') ? 'primary' : 'text'}
            size="small" icon={<DeleteOutlined />}
            onClick={() => navigate(`/w/${wid}/trash`)}
          >{!isMobile && '回收站'}</Button>
          <Button
            type={location.includes('/reports') ? 'primary' : 'text'}
            size="small" icon={<FileTextOutlined />}
            onClick={() => navigate(`/w/${wid}/reports`)}
          >{!isMobile && '报表'}</Button>
          <Tooltip title="成员管理">
            <Button
              type="text" size="small" icon={<TeamOutlined />}
              onClick={() => setMembersOpen(true)}
            />
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

      <Layout>
        <Sider
          collapsible collapsed={collapsed} onCollapse={setCollapsed}
          width={240} collapsedWidth={60}
          style={{ background: '#fafafa', borderRight: '1px solid #e5e7eb' }}
        >
          <div style={{
            padding: '12px 16px', borderBottom: '1px solid #e5e7eb',
            display: collapsed ? 'none' : 'flex', alignItems: 'center', gap: 8,
          }}>
            <Input prefix={<SearchOutlined />} placeholder="搜索表..." allowClear />
          </div>
          <div style={{ padding: '8px 16px', fontWeight: 600, color: '#6b7280', fontSize: 12, display: collapsed ? 'none' : 'block' }}>
            数据表 ({orderedTables.length})
          </div>
          {tables.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>
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
                onClick: () => navigate(`/w/${wid}/tables/${t.id}`),
              }))}
            />
          )}
        </Sider>

        <Content style={{ background: '#f5f7fa', overflow: 'auto', padding: 16 }}>
          <Outlet />
        </Content>
      </Layout>

      <Suspense fallback={<ModalFallback />}>
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <MembersModal open={membersOpen} wid={wid} onClose={() => setMembersOpen(false)} />
      </Suspense>
    </Layout>
  )
}

/** 用户设置面板 — API Token 管理 + 主题切换 + 工作区快捷入口. */

import { useState } from 'react'
import { Modal, Tabs, Table, Button, Input, Select, Space, message, Tag, Popconfirm, Empty, Tooltip, Switch } from 'antd'
import { PlusOutlined, DeleteOutlined, CopyOutlined, KeyOutlined, BulbOutlined, TeamOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tokenApi, workspaceApi } from '@/api'
import type { ApiToken, WorkspaceMember } from '@/api'
import { useTheme } from '@/theme/ThemeProvider'

interface Props {
  open: boolean
  onClose: () => void
  wid?: string
  onOpenMembers?: () => void
}

export default function SettingsModal({ open, onClose, wid, onOpenMembers }: Props) {
  const queryClient = useQueryClient()
  const { mode, toggle } = useTheme()
  const [newTokenName, setNewTokenName] = useState('')
  const [newExpiry, setNewExpiry] = useState<number | undefined>(30)

  const { data: tokens = [], isLoading } = useQuery<ApiToken[]>({
    queryKey: ['api-tokens'],
    queryFn: () => tokenApi.list(),
    enabled: open,
  })

  // 当前工作区成员概览（可选）
  const { data: members = [] } = useQuery<WorkspaceMember[]>({
    queryKey: ['workspace-members', wid],
    queryFn: () => workspaceApi.members(wid!),
    enabled: open && !!wid,
  })

  const createToken = useMutation({
    mutationFn: () => tokenApi.create({
      name: newTokenName.trim(),
      expires_days: newExpiry,
    }),
    onSuccess: () => {
      message.success('Token 已创建')
      setNewTokenName('')
      queryClient.invalidateQueries({ queryKey: ['api-tokens'] })
    },
  })

  const removeToken = useMutation({
    mutationFn: (id: number | string) => tokenApi.remove(id),
    onSuccess: () => {
      message.success('Token 已删除')
      queryClient.invalidateQueries({ queryKey: ['api-tokens'] })
    },
  })

  return (
    <Modal
      title="个人设置"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={600}
      destroyOnHidden
    >
      <Tabs
        items={[
          {
            key: 'tokens',
            label: <span><KeyOutlined /> API Token</span>,
            children: (
              <div>
                <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                  <Input
                    placeholder="Token 名称（例如：CI Pipeline）"
                    value={newTokenName}
                    onChange={e => setNewTokenName(e.target.value)}
                    style={{ flex: 1 }}
                  />
                  <Select
                    value={newExpiry}
                    onChange={setNewExpiry}
                    style={{ width: 140 }}
                    options={[
                      { value: 7, label: '7 天' },
                      { value: 30, label: '30 天' },
                      { value: 90, label: '90 天' },
                      { value: 365, label: '1 年' },
                      { value: undefined as unknown as number, label: '永久' },
                    ]}
                  />
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    disabled={!newTokenName.trim()}
                    loading={createToken.isPending}
                    onClick={() => createToken.mutate()}
                  >创建</Button>
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  loading={isLoading}
                  dataSource={tokens}
                  locale={{ emptyText: <Empty description="还没有 API Token" /> }}
                  pagination={false}
                  columns={[
                    { title: '名称', dataIndex: 'name', ellipsis: true },
                    {
                      title: 'Token', dataIndex: 'token', ellipsis: true,
                      render: (t: string) => {
                        const masked = t ? `${t.slice(0, 12)}${'*'.repeat(Math.max(0, t.length - 16))}${t.slice(-4)}` : ''
                        return (
                          <Space>
                            <code style={{ fontSize: 12, color: '#64748b' }}>{masked}</code>
                            <Tooltip title="复制完整 Token（创建后仅显示一次，此后只能删除重建）">
                              <Button size="small" type="text" icon={<CopyOutlined />}
                                onClick={() => navigator.clipboard?.writeText(t).then(() => message.success('已复制'))} />
                            </Tooltip>
                          </Space>
                        )
                      },
                    },
                    {
                      title: '过期', dataIndex: 'expires_at', width: 140,
                      render: (v: string | null, record) => (
                        record.expires_at ? (
                          <Tag color="orange">{new Date(v!).toLocaleDateString()}</Tag>
                        ) : <Tag>永久</Tag>
                      ),
                    },
                    {
                      title: '操作', width: 80,
                      render: (_, r) => (
                        <Popconfirm
                          title={`确定删除 Token「${r.name}」？`}
                          onConfirm={() => removeToken.mutate(r.id)}
                        >
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      ),
                    },
                  ]}
                />
                <div style={{ marginTop: 12, fontSize: 12, color: '#64748b' }}>
                  注意：Token 创建后完整值仅显示一次，请妥善保管。使用 Token 作为 HTTP Header：Authorization: Bearer &lt;token&gt;
                </div>
              </div>
            ),
          },
          {
            key: 'theme',
            label: <span><BulbOutlined /> 外观</span>,
            children: (
              <div style={{ padding: '24px 0' }}>
                <Space size="large">
                  <span>暗色模式</span>
                  <Switch checked={mode === 'dark'} onChange={toggle} />
                </Space>
                <div style={{ marginTop: 12, fontSize: 12, color: '#64748b' }}>
                  设置会自动保存到浏览器。
                </div>
              </div>
            ),
          },
          {
            key: 'workspace',
            label: <span><TeamOutlined /> 工作区</span>,
            disabled: !wid,
            children: !wid ? (
              <Empty description="请先选择一个工作区" style={{ padding: 32 }} />
            ) : (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                  <span>当前工作区共 {members.length} 位成员</span>
                  {onOpenMembers && (
                    <Button type="link" size="small" onClick={() => { onOpenMembers(); onClose() }}>
                      打开成员管理 →
                    </Button>
                  )}
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={members}
                  pagination={false}
                  locale={{ emptyText: <Empty description="暂无成员" /> }}
                  columns={[
                    { title: '用户名', dataIndex: 'username' },
                    {
                      title: '角色', dataIndex: 'role',
                      render: (r: string) => {
                        const color = r === 'owner' ? 'red' : r === 'admin' ? 'orange' : 'blue'
                        return <Tag color={color}>{r}</Tag>
                      },
                    },
                  ]}
                />
              </div>
            ),
          },
        ]}
      />
    </Modal>
  )
}

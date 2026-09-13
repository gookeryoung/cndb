/** 工作区设置对话框 — 基本设置 + 成员管理 + 统计信息（三 Tab）. */

import { useEffect, useMemo, useState } from 'react'
import { Modal, Tabs, Form, Input, Select, Switch, Tag, Button, Descriptions, Table, Empty, Input as AntInput, message, Popconfirm } from 'antd'
import { SettingOutlined, TeamOutlined, BarChartOutlined, PlusOutlined, UserDeleteOutlined, CrownOutlined, FileTextOutlined, EyeOutlined, ColumnWidthOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import type { WorkspaceDetail, WorkspaceMember, WorkspaceRole, WorkspaceVisibility } from '@/api'

interface Props {
  open: boolean
  wid: string
  onClose: () => void
  /** 设置保存后通知工作区列表刷新 */
  onUpdated?: () => void
}

const ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  viewer: '查看者',
}

const VISIBILITY_LABEL: Record<WorkspaceVisibility, string> = {
  public: '公开（任何人可读）',
  member: '成员可见（仅工作区成员可访问）',
  private: '私有（仅所有者和管理员可见）',
}

const ROLE_OPTIONS: Array<{ value: WorkspaceRole; label: string }> = (Object.keys(ROLE_LABEL) as WorkspaceRole[])
  .filter(r => r !== 'owner')
  .map(r => ({ value: r, label: ROLE_LABEL[r] }))

export default function WorkspaceSettingsModal({ open, wid, onClose, onUpdated }: Props) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [inviteName, setInviteName] = useState('')
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>('editor')
  const [activeTab, setActiveTab] = useState('basic')

  // 获取工作区详情
  const { data: detail } = useQuery<WorkspaceDetail>({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: open && !!wid,
  })

  // 获取成员列表
  const { data: members = [], isLoading: membersLoading } = useQuery<WorkspaceMember[]>({
    queryKey: ['workspace-members', wid],
    queryFn: () => workspaceApi.members(wid),
    enabled: open && !!wid,
  })

  // 打开时填充表单
  useEffect(() => {
    if (detail && open) {
      form.setFieldsValue({
        name: detail.name,
        description: detail.description,
        visibility: detail.visibility ?? 'member',
        tags: (detail.tags ?? []).join(', '),
        allow_edit: detail.allow_edit ?? true,
      })
    }
  }, [detail, open, form])

  // 保存设置
  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      const tagsStr = (v.tags as string) || ''
      return workspaceApi.update(wid, {
        name: v.name as string,
        description: v.description as string,
        visibility: v.visibility as WorkspaceVisibility,
        tags: tagsStr.split(/[,，]/).map(s => s.trim()).filter(Boolean),
        allow_edit: v.allow_edit as boolean,
      })
    },
    onSuccess: () => {
      message.success('设置已保存')
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      onUpdated?.()
    },
  })

  // 成员管理 mutations
  const invite = useMutation({
    mutationFn: ({ username, role }: { username: string; role: string }) => workspaceApi.addMember(wid, username, role),
    onSuccess: () => {
      message.success('已邀请用户')
      setInviteName('')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
  })

  const changeRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: number | string; role: string }) => workspaceApi.updateMemberRole(wid, memberId, role),
    onSuccess: () => {
      message.success('角色已更新')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
  })

  const kick = useMutation({
    mutationFn: (memberId: number | string) => workspaceApi.removeMember(wid, memberId),
    onSuccess: () => {
      message.success('已移除成员')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
  })

  const canEdit = detail?.visibility !== undefined  // 所有成员都能看设置，但编辑权限在按钮层控制

  // 统计展示
  const statItems = useMemo(() => {
    if (!detail) return []
    return [
      { label: '数据表', value: detail.table_count ?? 0, icon: <FileTextOutlined />, color: '#3b82f6' },
      { label: '成员', value: detail.member_count ?? 0, icon: <UserOutlined />, color: '#8b5cf6' },
      { label: '视图', value: detail.view_count ?? 0, icon: <EyeOutlined />, color: '#10b981' },
      { label: '数据行', value: detail.total_rows ?? 0, icon: <ColumnWidthOutlined />, color: '#f59e0b' },
    ]
  }, [detail])

  const tabs = [
    {
      key: 'basic',
      label: <span><SettingOutlined /> 基本设置</span>,
      children: (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ visibility: 'member', tags: '', allow_edit: true }}
          onFinish={(v) => save.mutate(v)}
        >
          <Form.Item
            name="name"
            label="工作区名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例如：产品研发" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} placeholder="简单介绍一下这个工作区" />
          </Form.Item>
          <Form.Item name="visibility" label="公开性">
            <Select options={Object.entries(VISIBILITY_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）">
            <Input placeholder="例如：研发, 产品, 核心业务" />
          </Form.Item>
          <Form.Item name="allow_edit" label="编辑权限" valuePropName="checked">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Switch />
              <span style={{ color: '#64748b', fontSize: 13 }}>
                {form.getFieldValue('allow_edit') ?? true
                  ? '已开启：允许编辑者和管理员修改数据'
                  : '已关闭：仅所有者可修改数据'}
              </span>
            </div>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'members',
      label: <span><TeamOutlined /> 成员管理</span>,
      children: (
        <div>
          {/* 邀请区域 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, padding: 12, background: '#f8fafc', borderRadius: 8 }}>
            <AntInput
              placeholder="输入用户名邀请"
              value={inviteName}
              onChange={e => setInviteName(e.target.value)}
              style={{ flex: 1 }}
            />
            <Select
              value={inviteRole}
              onChange={setInviteRole}
              style={{ width: 120 }}
              options={ROLE_OPTIONS}
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!inviteName.trim()}
              loading={invite.isPending}
              onClick={() => invite.mutate({ username: inviteName.trim(), role: inviteRole })}
            >邀请</Button>
          </div>

          {/* 成员列表 */}
          <Table
            rowKey="id"
            size="small"
            loading={membersLoading}
            dataSource={members}
            locale={{ emptyText: <Empty description="暂无成员" /> }}
            pagination={false}
            columns={[
              {
                title: '用户',
                render: (_, m) => (
                  <div>
                    <div style={{ fontWeight: 500 }}>{m.username}</div>
                    {m.email && <div style={{ color: '#94a3b8', fontSize: 12 }}>{m.email}</div>}
                  </div>
                ),
              },
              {
                title: '角色', width: 180,
                render: (_, m) => {
                  if (m.role === 'owner') {
                    return <Tag color="gold" icon={<CrownOutlined />}>{ROLE_LABEL[m.role]}</Tag>
                  }
                  return (
                    <Select
                      value={m.role}
                      onChange={(v: string) => changeRole.mutate({ memberId: m.id, role: v })}
                      size="small"
                      style={{ width: 140 }}
                      options={[...ROLE_OPTIONS, { value: 'owner', label: ROLE_LABEL.owner, disabled: true }]}
                    />
                  )
                },
              },
              {
                title: '操作', width: 80,
                render: (_, m) => m.role !== 'owner' ? (
                  <Popconfirm
                    title={`移除「${m.username}」？`}
                    onConfirm={() => kick.mutate(m.id)}
                  >
                    <Button size="small" type="text" danger icon={<UserDeleteOutlined />} />
                  </Popconfirm>
                ) : null,
              },
            ]}
          />
        </div>
      ),
    },
    {
      key: 'stats',
      label: <span><BarChartOutlined /> 统计信息</span>,
      children: (
        <div>
          {/* 统计卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 20 }}>
            {statItems.map(item => (
              <div
                key={item.label}
                style={{
                  padding: 16,
                  background: '#f8fafc',
                  borderRadius: 8,
                  borderLeft: `3px solid ${item.color}`,
                }}
              >
                <div style={{ fontSize: 12, color: '#64748b', display: 'flex', alignItems: 'center', gap: 4 }}>
                  {item.icon} {item.label}
                </div>
                <div style={{ fontSize: 24, fontWeight: 600, marginTop: 4 }}>
                  {item.value.toLocaleString()}
                </div>
              </div>
            ))}
          </div>

          {/* 拥有者信息 */}
          {detail?.owner && (
            <Descriptions title="拥有者" size="small" bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="用户名">{detail.owner.username}</Descriptions.Item>
              {detail.owner.nickname && (
                <Descriptions.Item label="昵称">{detail.owner.nickname}</Descriptions.Item>
              )}
            </Descriptions>
          )}

          {/* 创建信息（只读） */}
          <Descriptions title="工作区信息（只读）" size="small" bordered column={2}>
            <Descriptions.Item label="ID">{detail?.id}</Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {detail?.created_at ? new Date(detail.created_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="最后更新">
              {detail?.updated_at ? new Date(detail.updated_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="公开性">
              {VISIBILITY_LABEL[detail?.visibility ?? 'member']}
            </Descriptions.Item>
            <Descriptions.Item label="标签" span={2}>
              {(detail?.tags ?? []).length > 0
                ? (detail?.tags ?? []).map(t => <Tag key={t}>{t}</Tag>)
                : <span style={{ color: '#94a3b8' }}>暂无标签</span>}
            </Descriptions.Item>
          </Descriptions>
        </div>
      ),
    },
  ]

  return (
    <Modal
      title="工作区设置"
      open={open}
      onCancel={onClose}
      width={720}
      destroyOnHidden
      confirmLoading={save.isPending}
      footer={[
        <Button key="close" onClick={onClose}>关闭</Button>,
        canEdit && <Button key="save" type="primary" onClick={() => form.submit()} loading={save.isPending}>保存设置</Button>,
      ].filter(Boolean)}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabs}
      />
    </Modal>
  )
}

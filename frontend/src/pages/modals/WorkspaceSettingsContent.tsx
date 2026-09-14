/** 工作区设置 — 内容组件（可嵌入 Modal 或独立页面）.
 *
 * 包含三个 Tab：基本设置 / 成员管理 / 统计信息
 * 所有颜色均使用 CSS 变量，自动适配深浅主题。
 *
 * Props:
 *  - wid: 工作区 ID
 *  - initialTab: 初始激活的 Tab
 *  - onClose: （可选）在 Modal 模式下的关闭回调
 *  - embedded: 是否嵌入独立页面（非 Modal 模式），决定底部是否显示保存按钮
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Tabs, Form, Input, Select, Switch, Tag, Button, Descriptions,
  Table, Empty, message, Popconfirm, Divider,
} from 'antd'
import {
  SettingOutlined, TeamOutlined, BarChartOutlined, PlusOutlined,
  UserDeleteOutlined, CrownOutlined, FileTextOutlined, EyeOutlined,
  ColumnWidthOutlined, UserOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import type {
  WorkspaceDetail, WorkspaceMember, WorkspaceRole, WorkspaceVisibility,
  MemberUserBrief,
} from '@/api'
import { useAuth } from '@/auth/AuthContext'

interface Props {
  wid: string
  initialTab?: 'basic' | 'members' | 'stats'
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

/** 角色等级 — 数值越大权限越高 */
const ROLE_RANK: Record<WorkspaceRole, number> = { owner: 3, admin: 2, editor: 1, viewer: 0 }

/** 当前用户可分配给其他人的角色选项（不含比自己高的） */
function getAssignableRoles(currentRole: WorkspaceRole | null): Array<{ value: WorkspaceRole; label: string }> {
  if (!currentRole) return []
  const myRank = ROLE_RANK[currentRole]
  return (Object.keys(ROLE_LABEL) as WorkspaceRole[])
    .filter(r => ROLE_RANK[r] <= myRank && !(currentRole === 'admin' && r === 'owner'))
    .map(r => ({ value: r, label: ROLE_LABEL[r] }))
}

/** 成员排序：owner → admin → editor → viewer */
function sortMembersByRole(members: WorkspaceMember[]): WorkspaceMember[] {
  return [...members].sort((a, b) => ROLE_RANK[b.role] - ROLE_RANK[a.role])
}

export default function WorkspaceSettingsContent({
  wid, initialTab = 'basic', onUpdated,
}: Props) {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const [form] = Form.useForm()
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>('editor')
  const [activeTab, setActiveTab] = useState(initialTab)
  const [candidatesSearch, setCandidatesSearch] = useState('')

  // 获取工作区详情
  const { data: detail } = useQuery<WorkspaceDetail>({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })

  // 获取成员列表
  const { data: members = [], isLoading: membersLoading } = useQuery<WorkspaceMember[]>({
    queryKey: ['workspace-members', wid],
    queryFn: () => workspaceApi.members(wid),
    enabled: !!wid,
  })

  // 候选用户（邀请时搜索）
  const { data: candidatesData = [] as MemberUserBrief[], isLoading: candidatesLoading } = useQuery<MemberUserBrief[]>({
    queryKey: ['workspace-member-candidates', wid, candidatesSearch],
    queryFn: async () => {
      const res = await workspaceApi.memberCandidates(wid, candidatesSearch)
      return res.results
    },
    enabled: !!wid && !!detail?.current_user_role && ROLE_RANK[detail.current_user_role] >= ROLE_RANK.admin,
    gcTime: 0,
  })

  // 打开/切换时重置 Tab + 填充表单
  useEffect(() => {
    setActiveTab(initialTab)
    setCandidatesSearch('')
  }, [initialTab, wid])

  useEffect(() => {
    if (detail) {
      form.setFieldsValue({
        name: detail.name,
        description: detail.description,
        visibility: detail.visibility ?? 'member',
        tags: (detail.tags ?? []).join(', '),
        allow_edit: detail.allow_edit ?? true,
      })
    }
  }, [detail, form])

  // 当前用户角色
  const myRole = detail?.current_user_role ?? null
  const myRoleRank = myRole ? ROLE_RANK[myRole] : -1

  // 权限判断
  const canEditBasic = myRoleRank >= ROLE_RANK.admin
  const canManageMembers = myRoleRank >= ROLE_RANK.admin
  const canDeleteWorkspace = myRole === 'owner'
  const assignableRoles = useMemo(() => getAssignableRoles(myRole), [myRole])
  const sortedMembers = useMemo(() => sortMembersByRole(members), [members])

  const currentMemberId = members.find(
    m => m.user?.username === currentUser?.username,
  )?.id

  // mutations
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

  const invite = useMutation({
    mutationFn: ({ username, role }: { username: string; role: string }) =>
      workspaceApi.addMember(wid, username, role),
    onSuccess: () => {
      message.success('已邀请用户')
      setCandidatesSearch('')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
  })

  const changeRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: number | string; role: string }) =>
      workspaceApi.updateMemberRole(wid, memberId, role),
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

  const removeWs = useMutation({
    mutationFn: () => workspaceApi.remove(wid),
    onSuccess: () => {
      message.success('工作区已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })

  const statItems = useMemo(() => {
    if (!detail) return []
    return [
      { label: '数据表', value: detail.table_count ?? 0, icon: <FileTextOutlined />, color: 'var(--cn-brand-color)' },
      { label: '成员', value: detail.member_count ?? 0, icon: <UserOutlined />, color: '#8b5cf6' },
      { label: '视图', value: detail.view_count ?? 0, icon: <EyeOutlined />, color: '#10b981' },
      { label: '数据行', value: detail.total_rows ?? 0, icon: <ColumnWidthOutlined />, color: '#f59e0b' },
    ]
  }, [detail])

  // 公共样式常量
  const subtleBoxStyle: React.CSSProperties = {
    background: 'var(--cn-bg-subtle)',
    borderRadius: 8,
    border: '1px solid var(--cn-border-soft)',
  }
  const dangerBoxStyle: React.CSSProperties = {
    background: 'var(--cn-bg-danger-subtle)',
    borderRadius: 8,
    border: '1px solid #fecaca',
  }
  const warningBoxStyle: React.CSSProperties = {
    background: 'var(--cn-bg-warning-subtle)',
    borderRadius: 8,
  }

  // ─────────────────────────────────────────
  // 成员管理 Tab 内部组件
  const membersTabChildren = (
    <div>
      {/* 邀请区 — 搜索候选用户 */}
      {canManageMembers && (
        <div
          style={{
            display: 'flex', gap: 8, marginBottom: 16,
            padding: 12, ...subtleBoxStyle,
          }}
        >
          <Select
            showSearch
            filterOption={false}
            onSearch={setCandidatesSearch}
            placeholder="搜索用户名或昵称..."
            style={{ flex: 1 }}
            options={candidatesData.map(u => ({
              value: u.username,
              label: (
                <span>
                  <strong>{u.username}</strong>
                  {u.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8 }}>({u.nickname})</span>}
                </span>
              ),
            }))}
            notFoundContent={
              candidatesSearch
                ? (candidatesLoading ? '搜索中...' : '未找到候选用户')
                : '请输入关键字搜索可邀请的用户'
            }
            loading={candidatesLoading}
          />
          <Select
            value={inviteRole}
            onChange={setInviteRole}
            style={{ width: 140 }}
            options={assignableRoles.filter(r => r.value !== 'owner')}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!candidatesSearch}
            loading={invite.isPending}
            onClick={() => {
              const selected = candidatesData.find(u => u.username === candidatesSearch)
              if (selected) {
                invite.mutate({ username: selected.username, role: inviteRole })
              }
            }}
          >邀请</Button>
        </div>
      )}
      {!canManageMembers && (
        <div style={{ marginBottom: 16, padding: 12, ...warningBoxStyle, color: '#92400e' }}>
          仅管理员及以上角色可管理成员
        </div>
      )}

      {/* 成员列表 */}
      <Table
        rowKey="id"
        size="small"
        loading={membersLoading}
        dataSource={sortedMembers}
        locale={{ emptyText: <Empty description="暂无成员" /> }}
        pagination={false}
        columns={[
          {
            title: '用户',
            render: (_, m) => {
              const u = m.user
              const isMe = currentMemberId === m.id
              return (
                <div>
                  <div style={{ fontWeight: 500 }}>
                    {u.username}
                    {u.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8, fontSize: 13 }}>({u.nickname})</span>}
                    {isMe && <Tag color="blue" style={{ marginLeft: 8 }}>我</Tag>}
                  </div>
                  {u.email && <div style={{ color: 'var(--cn-text-muted)', fontSize: 12 }}>{u.email}</div>}
                </div>
              )
            },
          },
          {
            title: '角色', width: 180,
            render: (_, m) => {
              const isOwner = m.role === 'owner'
              if (isOwner) {
                return <Tag color="gold" icon={<CrownOutlined />}>{ROLE_LABEL[m.role]}</Tag>
              }
              if (!canManageMembers) {
                return <Tag>{ROLE_LABEL[m.role]}</Tag>
              }
              return (
                <Select
                  value={m.role}
                  onChange={(v: string) => changeRole.mutate({ memberId: m.id, role: v })}
                  size="small"
                  style={{ width: 140 }}
                  disabled={myRoleRank < ROLE_RANK.admin || (m.role === 'owner' && myRole !== 'owner')}
                  options={assignableRoles}
                />
              )
            },
          },
          {
            title: '操作', width: 80,
            render: (_, m) => {
              if (m.role === 'owner') return null
              if (!canManageMembers) return null
              if (myRole === 'admin' && m.role === 'admin') return null
              return (
                <Popconfirm
                  title={`移除「${m.user.username}」？`}
                  description="该成员将从工作区中移出"
                  onConfirm={() => kick.mutate(m.id)}
                >
                  <Button size="small" type="text" danger icon={<UserDeleteOutlined />} />
                </Popconfirm>
              )
            },
          },
        ]}
      />
    </div>
  )

  // ─────────────────────────────────────────
  // Tab 定义
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
          disabled={!canEditBasic}
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
            <Select
              options={Object.entries(VISIBILITY_LABEL).map(([v, l]) => ({ value: v, label: l }))}
              disabled={!canEditBasic}
            />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）">
            <Input placeholder="例如：研发, 产品, 核心业务" />
          </Form.Item>
          <Form.Item name="allow_edit" label="编辑权限" valuePropName="checked">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Switch disabled={!canEditBasic} />
              <span style={{ color: 'var(--cn-text-secondary)', fontSize: 13 }}>
                {form.getFieldValue('allow_edit') ?? true
                  ? '已开启：允许编辑者和管理员修改数据'
                  : '已关闭：仅所有者可修改数据'}
              </span>
            </div>
          </Form.Item>
          {!canEditBasic && (
            <div style={{ marginTop: 12, color: '#f59e0b', fontSize: 13 }}>
              ℹ️ 您的角色（{ROLE_LABEL[myRole ?? 'viewer']}）仅能查看设置，无法修改
            </div>
          )}
        </Form>
      ),
    },
    {
      key: 'members',
      label: <span><TeamOutlined /> 成员管理</span>,
      children: membersTabChildren,
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
                  ...subtleBoxStyle,
                  borderLeft: `3px solid ${item.color}`,
                }}
              >
                <div style={{ fontSize: 12, color: 'var(--cn-text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  {item.icon} {item.label}
                </div>
                <div style={{ fontSize: 24, fontWeight: 600, marginTop: 4, color: 'var(--cn-text-primary)' }}>
                  {item.value.toLocaleString()}
                </div>
              </div>
            ))}
          </div>

          {/* 当前角色 + 拥有者 */}
          <Descriptions title="角色信息" size="small" bordered column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="您的角色">
              {myRole
                ? <Tag color={myRole === 'owner' ? 'gold' : myRole === 'admin' ? 'geekblue' : 'default'}>{ROLE_LABEL[myRole]}</Tag>
                : <Tag>非成员</Tag>}
            </Descriptions.Item>
            {detail?.owner && (
              <Descriptions.Item label="拥有者">
                {detail.owner.username}
                {detail.owner.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8 }}>({detail.owner.nickname})</span>}
              </Descriptions.Item>
            )}
          </Descriptions>

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
                : <span style={{ color: 'var(--cn-text-muted)' }}>暂无标签</span>}
            </Descriptions.Item>
          </Descriptions>

          {/* 危险操作区 — 仅 owner 可见 */}
          {canDeleteWorkspace && (
            <>
              <Divider />
              <div style={{ padding: 16, ...dangerBoxStyle }}>
                <div style={{ fontWeight: 600, color: '#dc2626', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <DeleteOutlined /> 危险操作
                </div>
                <div style={{ color: '#991b1b', fontSize: 13, marginBottom: 12 }}>
                  删除工作区将永久删除所有数据表、数据行、视图和成员关系，无法恢复。
                </div>
                <Popconfirm
                  title={`确认删除工作区「${detail?.name}」？`}
                  description="此操作不可撤销，所有数据将永久丢失。"
                  okText="我确定，删除"
                  okType="danger"
                  cancelText="取消"
                  onConfirm={() => removeWs.mutate()}
                >
                  <Button danger icon={<DeleteOutlined />} loading={removeWs.isPending}>
                    删除工作区
                  </Button>
                </Popconfirm>
              </div>
            </>
          )}
        </div>
      ),
    },
  ]

  const footerButtons = canEditBasic
    ? [
      <Button
        key="save"
        type="primary"
        onClick={() => form.submit()}
        loading={save.isPending}
      >保存设置</Button>,
    ]
    : []

  return (
    <div className="workspace-settings-content">
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as typeof initialTab)}
        items={tabs}
      />
      {footerButtons.length > 0 && (
        <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
          {footerButtons}
        </div>
      )}
    </div>
  )
}

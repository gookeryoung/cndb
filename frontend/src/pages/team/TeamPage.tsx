/** 团队页（ADR 0153 P1）—— 多工作区统一管理入口.
 *
 * 口径（与后端一致）：
 * - 团队单层扁平、工作区在团队下是**平铺列表**（无树，D2 / C1）；
 * - 团队角色只决定管理面：`team_owner` 改设置 / 策略 / 成员，`team_admin` 管成员，
 *   `team_member` 只读；团队管理员默认**读不到工作区数据**（D4），页面明确提示；
 * - 删除团队只解绑工作区（D9），文案必须说清「不删工作区数据」。
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  App as AntApp, Button, Card, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select,
  Space, Switch, Table, Tag, Typography, type FormInstance,
} from 'antd'
import {
  DeleteOutlined, FileSearchOutlined, FileTextOutlined, PlusOutlined, TableOutlined, TeamOutlined,
  UserAddOutlined,
} from '@ant-design/icons'

import { teamApi, workspaceApi } from '@/api'
import type { Team, TeamMember, TeamPolicy, TeamRole } from '@/api'
import HelpTip from '@/components/HelpTip'
import { useResponsive } from '@/hooks/useResponsive'

const { Text, Title } = Typography

const TEAM_ROLE_LABEL: Record<TeamRole, string> = {
  owner: '团队所有者',
  admin: '团队管理员',
  member: '团队成员',
}

const TEAM_ROLE_COLOR: Record<TeamRole, string> = {
  owner: 'gold',
  admin: 'blue',
  member: 'default',
}

const MODULE_LABEL: Record<string, string> = {
  tables: '数据表',
  documents: '文档',
  design: '设计',
}

export default function TeamPage() {
  const queryClient = useQueryClient()
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const [selectedId, setSelectedId] = useState<number | string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [policyForm] = Form.useForm()
  const [searchText, setSearchText] = useState('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [addMemberName, setAddMemberName] = useState('')
  const [addMemberRole, setAddMemberRole] = useState<'admin' | 'member'>('member')

  const { data: teams = [], isLoading } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
  })

  const active: Team | null = useMemo(() => {
    if (!teams.length) return null
    return teams.find(t => String(t.id) === String(selectedId)) ?? teams[0]
  }, [teams, selectedId])

  const tid = active?.id
  const isOwner = active?.current_user_role === 'owner'
  const canManageMembers = isOwner || active?.current_user_role === 'admin'

  const { data: members = [], isLoading: membersLoading } = useQuery<TeamMember[]>({
    queryKey: ['team-members', tid],
    queryFn: () => teamApi.members(tid as number | string),
    enabled: !!tid,
  })

  const { data: workspaces = [] } = useQuery({
    queryKey: ['team-workspaces', tid],
    queryFn: () => teamApi.workspaces(tid as number | string),
    enabled: !!tid,
  })

  const { data: searchResult, isFetching: searchLoading } = useQuery({
    queryKey: ['team-search', tid, searchKeyword],
    queryFn: () => teamApi.search(tid as number | string, searchKeyword),
    enabled: !!tid && !!searchKeyword.trim(),
    staleTime: 15_000,
  })

  const joinWorkspace = useMutation({
    mutationFn: (wid: number | string) => workspaceApi.join(wid),
    onSuccess: () => {
      message.success('已加入工作区')
      queryClient.invalidateQueries({ queryKey: ['teams'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      queryClient.invalidateQueries({ queryKey: ['team-workspaces', tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '加入工作区失败'),
  })

  const invalidateTeam = () => {
    queryClient.invalidateQueries({ queryKey: ['teams'] })
    queryClient.invalidateQueries({ queryKey: ['team-members', tid] })
    queryClient.invalidateQueries({ queryKey: ['team-workspaces', tid] })
    // 团队变更影响工作区能力位（管理面）与列表分组
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const create = useMutation({
    mutationFn: (values: { name: string; description?: string }) => teamApi.create(values),
    onSuccess: (team) => {
      message.success(`已创建团队「${team.name}」`)
      setCreateOpen(false)
      createForm.resetFields()
      setSelectedId(team.id)
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建团队失败'),
  })

  const savePolicy = useMutation({
    mutationFn: (policy: TeamPolicy) => teamApi.update(tid as number | string, { policy }),
    onSuccess: () => {
      message.success('团队策略已保存')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存策略失败'),
  })

  const removeTeam = useMutation({
    mutationFn: () => teamApi.remove(tid as number | string),
    onSuccess: () => {
      message.success('团队已删除，其工作区已转为独立工作区（数据未删除）')
      setSelectedId(null)
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除团队失败'),
  })

  const addMember = useMutation({
    mutationFn: () => teamApi.addMember(tid as number | string, addMemberName.trim(), addMemberRole),
    onSuccess: () => {
      message.success('已添加团队成员')
      setAddMemberName('')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '添加成员失败'),
  })

  const changeRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: number | string; role: string }) =>
      teamApi.updateMember(tid as number | string, memberId, role),
    onSuccess: () => {
      message.success('角色已更新')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新角色失败'),
  })

  const kick = useMutation({
    mutationFn: (memberId: number | string) => teamApi.removeMember(tid as number | string, memberId),
    onSuccess: () => {
      message.success('已移除团队成员（其工作区成员身份不受影响）')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '移除成员失败'),
  })

  if (!isLoading && teams.length === 0) {
    return (
      <div style={{ padding: 24 }} data-testid="team-page-empty">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="还没有团队。团队用于统一管理多个工作区的成员与策略（不会改变工作区内的权限）。"
        >
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建团队
          </Button>
        </Empty>
        <CreateTeamModal
          open={createOpen}
          form={createForm}
          onCancel={() => setCreateOpen(false)}
          onOk={(v) => create.mutate(v)}
          loading={create.isPending}
        />
      </div>
    )
  }

  return (
    <div style={{ padding: isMobile ? 12 : 24 }} data-testid="team-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, gap: 12 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <TeamOutlined style={{ marginRight: 8 }} />团队
          </Title>
          <Text type="secondary">统一管理多个工作区的成员与策略；工作区内的权限分配不变</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)} data-testid="create-team-btn">
          新建团队
        </Button>
      </div>

      <div style={{ display: 'flex', gap: 16, flexDirection: isMobile ? 'column' : 'row', alignItems: 'flex-start' }}>
        <Card
          size="small"
          title="我的团队"
          style={{ width: isMobile ? '100%' : 240, flex: '0 0 auto' }}
          loading={isLoading}
        >
          <Space direction="vertical" style={{ width: '100%' }} size={4}>
            {teams.map(team => (
              <Button
                key={team.id}
                type={String(team.id) === String(active?.id) ? 'default' : 'text'}
                block
                style={{ justifyContent: 'space-between', display: 'flex' }}
                onClick={() => setSelectedId(team.id)}
                data-testid={`team-item-${team.id}`}
              >
                <span>{team.name}</span>
                <Tag color={TEAM_ROLE_COLOR[team.current_user_role ?? 'member']} style={{ marginInlineEnd: 0 }}>
                  {TEAM_ROLE_LABEL[team.current_user_role ?? 'member']}
                </Tag>
              </Button>
            ))}
          </Space>
        </Card>

        <div style={{ flex: 1, width: '100%', minWidth: 0 }}>
          {active && (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Card
                size="small"
                title={
                  <Space>
                    {active.name}
                    <Tag color={TEAM_ROLE_COLOR[active.current_user_role ?? 'member']}>
                      {TEAM_ROLE_LABEL[active.current_user_role ?? 'member']}
                    </Tag>
                  </Space>
                }
                extra={
                  isOwner && (
                    <Popconfirm
                      title="删除团队？"
                      description="工作区会转为独立工作区，成员与数据都不会被删除。"
                      onConfirm={() => removeTeam.mutate()}
                      okText="删除团队"
                      cancelText="取消"
                    >
                      <Button danger size="small" icon={<DeleteOutlined />} data-testid="delete-team-btn">
                        删除团队
                      </Button>
                    </Popconfirm>
                  )
                }
              >
                <Space direction="vertical" size={4}>
                  <Text type="secondary">
                    团队成员 {active.member_count} 人 · 工作区 {active.workspace_count} 个 · 标识 {active.slug}
                  </Text>
                  <Text type="secondary">
                    <HelpTip title="团队角色只决定管理面：所有者可改团队设置与策略，管理员可管成员；两者默认都读不到工作区数据（数据权限仍由工作区成员角色决定）。" />
                    团队管理员默认看不到工作区数据
                  </Text>
                </Space>
              </Card>

              <Card size="small" title="团队成员">
                {canManageMembers && (
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Input
                      placeholder="按用户名添加成员"
                      value={addMemberName}
                      onChange={e => setAddMemberName(e.target.value)}
                      style={{ width: 200 }}
                      data-testid="team-add-member-input"
                    />
                    <Select
                      value={addMemberRole}
                      onChange={setAddMemberRole}
                      style={{ width: 120 }}
                      options={[
                        { value: 'member', label: '团队成员' },
                        { value: 'admin', label: '团队管理员' },
                      ]}
                    />
                    <Button
                      icon={<UserAddOutlined />}
                      disabled={!addMemberName.trim()}
                      loading={addMember.isPending}
                      onClick={() => addMember.mutate()}
                      data-testid="team-add-member-btn"
                    >
                      添加
                    </Button>
                  </Space>
                )}
                <Table<TeamMember>
                  size="small"
                  rowKey="id"
                  loading={membersLoading}
                  dataSource={members}
                  pagination={false}
                  columns={[
                    {
                      title: '成员',
                      dataIndex: ['user', 'username'],
                      render: (_: unknown, m) => m.user?.nickname || m.user?.username,
                    },
                    {
                      title: '团队角色',
                      dataIndex: 'role',
                      width: 180,
                      render: (role: TeamRole, m) =>
                        isOwner ? (
                          <Select
                            size="small"
                            value={role}
                            style={{ width: 140 }}
                            onChange={(next) => changeRole.mutate({ memberId: m.id, role: next })}
                            options={[
                              { value: 'owner', label: '团队所有者' },
                              { value: 'admin', label: '团队管理员' },
                              { value: 'member', label: '团队成员' },
                            ]}
                          />
                        ) : (
                          <Tag color={TEAM_ROLE_COLOR[role]}>{TEAM_ROLE_LABEL[role]}</Tag>
                        ),
                    },
                    {
                      title: '操作',
                      width: 90,
                      render: (_: unknown, m) =>
                        canManageMembers ? (
                          <Popconfirm
                            title="移出团队？"
                            description="只移除团队身份，不影响其在各工作区里的成员角色。"
                            onConfirm={() => kick.mutate(m.id)}
                            okText="移出"
                            cancelText="取消"
                          >
                            <Button size="small" type="text" danger>
                              移出
                            </Button>
                          </Popconfirm>
                        ) : null,
                    },
                  ]}
                />
              </Card>

              <Card size="small" title="团队下的工作区（平铺列表）">
                {workspaces.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该团队还没有工作区" />
                ) : (
                  <Table
                    size="small"
                    rowKey="id"
                    dataSource={workspaces}
                    pagination={false}
                    columns={[
                      {
                        title: '工作区',
                        dataIndex: 'name',
                        render: (name: string, ws: { id: number | string }) => (
                          <Link to={`/w/${ws.id}`}>{name}</Link>
                        ),
                      },
                      {
                        title: '模块',
                        dataIndex: 'modules',
                        render: (modules: string[]) => (
                          <Space size={4} wrap>
                            {modules.map(m => <Tag key={m}>{MODULE_LABEL[m] ?? m}</Tag>)}
                          </Space>
                        ),
                      },
                      { title: '成员', dataIndex: 'member_count', width: 80 },
                      {
                        title: '操作',
                        width: 120,
                        render: (_: unknown, ws: { id: number | string; is_member?: boolean }) =>
                          ws.is_member ? (
                            <Text type="secondary">已加入</Text>
                          ) : active.policy.allow_member_invite ? (
                            <Button
                              size="small"
                              type="link"
                              loading={joinWorkspace.isPending}
                              onClick={() => joinWorkspace.mutate(ws.id)}
                              data-testid={`join-workspace-${ws.id}`}
                            >
                              加入
                            </Button>
                          ) : (
                            <Text type="secondary">未加入</Text>
                          ),
                      },
                    ]}
                  />
                )}
              </Card>

              <Card size="small" title="团队内搜索">
                <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
                  <Input
                    placeholder="在团队内所有我能访问的工作区里搜索文档 / 数据表"
                    value={searchText}
                    onChange={e => setSearchText(e.target.value)}
                    onPressEnter={() => setSearchKeyword(searchText.trim())}
                    data-testid="team-search-input"
                  />
                  <Button
                    onClick={() => setSearchKeyword(searchText.trim())}
                    loading={searchLoading}
                    data-testid="team-search-btn"
                  >
                    搜索
                  </Button>
                </Space.Compact>
                {searchKeyword ? (
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    {(searchResult?.documents ?? []).map(doc => (
                      <Link key={`doc-${doc.id}`} to={`/w/${doc.workspace_id}/documents/${doc.id}`}>
                        <FileTextOutlined /> {doc.title}
                        <Text type="secondary"> · {doc.workspace_name}</Text>
                      </Link>
                    ))}
                    {(searchResult?.tables ?? []).map(table => (
                      <Link key={`table-${table.workspace_id}-${table.id}`} to={`/w/${table.workspace_id}/tables/${table.id}`}>
                        <TableOutlined /> {table.name}
                        <Text type="secondary"> · {table.workspace_name}</Text>
                      </Link>
                    ))}
                    {(searchResult?.rows ?? []).map(row => (
                      <Link
                        key={`row-${row.workspace_id}-${row.row_id}`}
                        to={`/w/${row.workspace_id}/tables`}
                      >
                        <FileSearchOutlined /> {row.title}
                        <Text type="secondary"> · {row.workspace_name} / {row.table_name}</Text>
                      </Link>
                    ))}
                    {!searchLoading &&
                      (searchResult?.documents?.length ?? 0) +
                        (searchResult?.tables?.length ?? 0) +
                        (searchResult?.rows?.length ?? 0) ===
                        0 && <Text type="secondary">没有匹配结果（只检索你有权访问的工作区）</Text>}
                  </Space>
                ) : (
                  <Text type="secondary">团队管理员默认看不到数据，搜索只覆盖你本人可读的工作区</Text>
                )}
              </Card>

              <Card
                size="small"
                title="团队策略"
                extra={!isOwner && <Text type="secondary">仅团队所有者可修改</Text>}
              >
                <Form
                  form={policyForm}
                  layout="vertical"
                  disabled={!isOwner}
                  initialValues={{
                    default_workspace_role: active.policy.default_workspace_role,
                    allow_member_invite: active.policy.allow_member_invite,
                    default_storage_quota_mb: active.policy.default_storage_quota_bytes
                      ? Math.round(active.policy.default_storage_quota_bytes / (1024 * 1024))
                      : null,
                  }}
                  onFinish={(values) => {
                    savePolicy.mutate({
                      default_workspace_role: values.default_workspace_role,
                      allow_member_invite: values.allow_member_invite,
                      allowed_modules: active.policy.allowed_modules,
                      default_storage_quota_bytes: values.default_storage_quota_mb
                        ? Number(values.default_storage_quota_mb) * 1024 * 1024
                        : null,
                    })
                  }}
                >
                  <Form.Item
                    label="团队成员默认角色"
                    name="default_workspace_role"
                    extra="只对「未被加为该工作区成员」的团队成员生效；显式成员角色永远优先"
                  >
                    <Select
                      options={[
                        { value: 'none', label: '看不到（默认，推荐）' },
                        { value: 'viewer', label: '可查看' },
                        { value: 'editor', label: '可编辑' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label="允许团队成员自助加入团队工作区" name="allow_member_invite" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item label="新工作区默认配额（MB）" name="default_storage_quota_mb" extra="留空表示沿用系统默认 100MB">
                    <InputNumber min={1} style={{ width: 180 }} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={savePolicy.isPending} data-testid="save-team-policy">
                    保存策略
                  </Button>
                </Form>
              </Card>
            </Space>
          )}
        </div>
      </div>

      <CreateTeamModal
        open={createOpen}
        form={createForm}
        onCancel={() => setCreateOpen(false)}
        onOk={(v) => create.mutate(v)}
        loading={create.isPending}
      />
    </div>
  )
}

function CreateTeamModal({
  open, form, onCancel, onOk, loading,
}: {
  open: boolean
  form: FormInstance<{ name: string; description?: string }>
  onCancel: () => void
  onOk: (values: { name: string; description?: string }) => void
  loading: boolean
}) {
  return (
    <ModalShell open={open} onCancel={onCancel} onOk={() => form.submit()} loading={loading} title="新建团队">
      <Form form={form} layout="vertical" onFinish={onOk}>
        <Form.Item name="name" label="团队名称" rules={[{ required: true, message: '请输入团队名称' }]}>
          <Input placeholder="例如：研发部" maxLength={128} />
        </Form.Item>
        <Form.Item name="description" label="描述（可选）">
          <Input.TextArea rows={2} maxLength={200} />
        </Form.Item>
      </Form>
    </ModalShell>
  )
}

function ModalShell({
  open, title, children, onCancel, onOk, loading,
}: {
  open: boolean
  title: string
  children: ReactNode
  onCancel: () => void
  onOk: () => void
  loading: boolean
}) {
  return (
    <Modal open={open} title={title} onCancel={onCancel} onOk={onOk} confirmLoading={loading} destroyOnHidden>
      {children}
    </Modal>
  )
}

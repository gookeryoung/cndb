/** 用户管理页 — 用户列表 / 编辑 / 批量操作 / 操作日志（权限变更历史）.
 *
 * 由 AdminPanel 以「用户管理」Tab 挂载，门控在 AdminPanel（仅系统管理员可见）。
 * 所有写操作经 modal.confirm 二次确认，变更由后端记录操作日志。
 */

import { useMemo, useState, type Key } from 'react'
import {
  Table, Button, Input, Select, Space, Tag, Modal, Form, Switch,
  App as AntApp, Typography, Drawer, Alert, Popconfirm,
} from 'antd'
import { EditOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi } from '@/api'
import type {
  UserAdminRecord, UserRole, UserAuditLogRecord, BatchUserActionRequest, UserAdminUpdateRequest,
} from '@/api'

const { Text } = Typography

const ROLE_OPTIONS: { value: UserRole; label: string; color: string }[] = [
  { value: 'system_admin', label: '系统管理员', color: 'red' },
  { value: 'security_admin', label: '安全管理员', color: 'orange' },
  { value: 'audit_admin', label: '审计管理员', color: 'blue' },
  { value: 'user', label: '普通用户', color: 'default' },
]

const ACTION_LABELS: Record<string, string> = {
  update: '资料编辑',
  role_change: '角色变更',
  activate: '启用',
  deactivate: '禁用',
  batch: '批量操作',
}

function roleMeta(role: string) {
  return ROLE_OPTIONS.find(r => r.value === role) ?? ROLE_OPTIONS[3]
}

/** 展示 before/after 变更差异摘要（权限变更历史追溯用） */
function DiffSummary({ log }: { log: UserAuditLogRecord }) {
  const detail = log.detail as {
    before?: Record<string, unknown>
    after?: Record<string, unknown>
    action?: string
    succeeded?: number
    failed?: number
    results?: { username: string; success: boolean; error?: string | null }[]
  }
  if (log.action === 'batch') {
    return (
      <div style={{ fontSize: 12 }}>
        <div>动作：{ACTION_LABELS[detail.action ?? ''] ?? detail.action}（成功 {detail.succeeded ?? 0} / 失败 {detail.failed ?? 0}）</div>
        {(detail.results ?? []).map((r, i) => (
          <div key={i}>
            - {r.username}：{r.success ? '成功' : `失败（${r.error ?? '未知原因'}）`}
          </div>
        ))}
      </div>
    )
  }
  const before = detail.before ?? {}
  const after = detail.after ?? {}
  const fields = Object.keys(after)
  return (
    <div style={{ fontSize: 12 }}>
      {fields.map(f => (
        <div key={f}>
          {f}: {String(before[f] ?? '—')} → {String(after[f] ?? '—')}
        </div>
      ))}
    </div>
  )
}

interface EditFormValues {
  username: string
  email?: string
  phone?: string
  nickname?: string
  role: UserRole
  is_active: boolean
}

export default function UsersPage() {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<EditFormValues>()

  // ── 列表筛选/分页状态 ──
  const [keyword, setKeyword] = useState('')
  const [roleFilter, setRoleFilter] = useState<UserRole | undefined>()
  const [activeFilter, setActiveFilter] = useState<boolean | undefined>()
  const [page, setPage] = useState(1)
  const pageSize = 20
  const [selectedIds, setSelectedIds] = useState<Key[]>([])

  // ── 编辑弹窗 ──
  const [editing, setEditing] = useState<UserAdminRecord | null>(null)

  // ── 日志抽屉（单用户） ──
  const [logTarget, setLogTarget] = useState<UserAdminRecord | null>(null)

  const listQuery = useQuery({
    queryKey: ['users', { keyword, roleFilter, activeFilter, page, pageSize }],
    queryFn: () => authApi.listUsers({
      keyword: keyword || undefined,
      role: roleFilter,
      is_active: activeFilter,
      page,
      page_size: pageSize,
    }),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
    queryClient.invalidateQueries({ queryKey: ['user-audit-logs'] })
  }

  const editMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: UserAdminUpdateRequest }) => authApi.editUser(id, data),
    onSuccess: () => {
      message.success('用户已更新，变更已记录到操作日志')
      setEditing(null)
      invalidate()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '更新失败')
    },
  })

  const batchMutation = useMutation({
    mutationFn: (data: BatchUserActionRequest) => authApi.batchUsers(data),
    onSuccess: (res) => {
      if (res.failed === 0) {
        message.success(`批量操作完成：成功 ${res.succeeded} 项`)
      } else {
        message.warning(`批量操作完成：成功 ${res.succeeded} 项，失败 ${res.failed} 项（详见操作日志）`)
      }
      setSelectedIds([])
      invalidate()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '批量操作失败')
    },
  })

  const logsQuery = useQuery({
    queryKey: ['user-audit-logs', logTarget?.id],
    queryFn: () => authApi.listUserAuditLogs(logTarget!.id as number, { page_size: 50 }),
    enabled: !!logTarget,
  })

  const roleOptions = useMemo(
    () => ROLE_OPTIONS.map(r => ({ value: r.value, label: r.label })),
    [],
  )

  const openEdit = (record: UserAdminRecord) => {
    setEditing(record)
    form.setFieldsValue({
      username: record.username,
      email: record.email ?? '',
      phone: record.phone ?? '',
      nickname: record.nickname,
      role: record.role,
      is_active: record.is_active,
    })
  }

  /** 编辑提交 —— 先做二次确认（展示变更摘要），确认后才调用后端 */
  const handleEditSubmit = () => {
    form.validateFields().then((values) => {
      if (!editing) return
      const changes: string[] = []
      if (values.username !== editing.username) changes.push(`用户名 ${editing.username} → ${values.username}`)
      if ((values.email ?? '') !== (editing.email ?? '')) changes.push('邮箱')
      if ((values.phone ?? '') !== (editing.phone ?? '')) changes.push(`电话 ${editing.phone ?? '—'} → ${values.phone || '—'}`)
      if (values.nickname !== editing.nickname) changes.push('昵称')
      if (values.role !== editing.role) changes.push(`角色 ${roleMeta(editing.role).label} → ${roleMeta(values.role).label}`)
      if (values.is_active !== editing.is_active) changes.push(values.is_active ? '状态 → 启用' : '状态 → 禁用')
      if (changes.length === 0) {
        message.info('没有需要保存的变更')
        return
      }
      Modal.confirm({
        title: '确认保存对该用户的修改？',
        content: (
          <div style={{ fontSize: 13 }}>
            <div style={{ marginBottom: 8 }}>目标用户：<Text strong>{editing.username}</Text></div>
            {changes.map(c => <div key={c}>· {c}</div>)}
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">本次变更将写入操作日志，可在「操作日志」中追溯。</Text>
            </div>
          </div>
        ),
        okText: '确认保存',
        cancelText: '取消',
        onOk: () => editMutation.mutateAsync({ id: editing.id as number, data: values }),
      })
    })
  }

  /** 批量操作 —— 统一二次确认 */
  const confirmBatch = (action: BatchUserActionRequest['action'], role?: UserRole) => {
    const ids = selectedIds.map(Number)
    if (ids.length === 0) return
    const title = action === 'activate' ? '确认批量启用所选用户？'
      : action === 'deactivate' ? '确认批量禁用所选用户？'
        : `确认将所选用户角色批量变更为「${roleMeta(role ?? 'user').label}」？`
    Modal.confirm({
      title,
      content: '操作将逐项执行并记录到操作日志；不能作用于当前登录用户与最后一个可用超管。',
      okText: '确认执行',
      okType: action === 'deactivate' ? 'danger' : 'primary',
      cancelText: '取消',
      onOk: () => batchMutation.mutateAsync({ action, user_ids: ids, role }),
    })
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', width: 140 },
    { title: '昵称', dataIndex: 'nickname', width: 120 },
    { title: '邮箱', dataIndex: 'email', width: 180, render: (v: string | null) => v ?? '—' },
    { title: '电话', dataIndex: 'phone', width: 120, render: (v: string | null) => v ?? '—' },
    {
      title: '角色', dataIndex: 'role', width: 110,
      render: (role: string, record: UserAdminRecord) => (
        <Space size={4}>
          <Tag color={roleMeta(role).color} style={{ marginRight: 0 }}>{roleMeta(role).label}</Tag>
          {record.is_superuser && <Tag color="purple" style={{ marginRight: 0 }}>超管</Tag>}
        </Space>
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', width: 80,
      render: (active: boolean) =>
        active ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: unknown, record: UserAdminRecord) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button size="small" type="link" onClick={() => setLogTarget(record)}>
            日志
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div data-testid="users-page">
      {/* 工具栏：筛选 + 批量操作 */}
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="搜索用户名/邮箱/昵称"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => { setKeyword(v); setPage(1) }}
        />
        <Select
          placeholder="角色筛选"
          allowClear
          style={{ width: 140 }}
          options={roleOptions}
          value={roleFilter}
          onChange={(v) => { setRoleFilter(v); setPage(1) }}
        />
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: 120 }}
          options={[
            { value: 'true', label: '启用' },
            { value: 'false', label: '禁用' },
          ]}
          value={activeFilter === undefined ? undefined : String(activeFilter)}
          onChange={(v) => { setActiveFilter(v === undefined ? undefined : v === 'true'); setPage(1) }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => invalidate()}>刷新</Button>
      </Space>

      {selectedIds.length > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={(
            <Space wrap>
              <span>已选择 {selectedIds.length} 个用户：</span>
              <Popconfirm title="确认批量启用所选用户？" okText="确认" cancelText="取消" onConfirm={() => confirmBatch('activate')}>
                <Button size="small">批量启用</Button>
              </Popconfirm>
              <Popconfirm
                title="确认批量禁用所选用户？"
                description="禁用后用户立即无法登录"
                okText="确认禁用"
                okType="danger"
                cancelText="取消"
                onConfirm={() => confirmBatch('deactivate')}
              >
                <Button size="small" danger>批量禁用</Button>
              </Popconfirm>
              {ROLE_OPTIONS.map(r => (
                <Popconfirm
                  key={r.value}
                  title={`确认将所选用户角色变更为「${r.label}」？`}
                  okText="确认"
                  cancelText="取消"
                  onConfirm={() => confirmBatch('set_role', r.value)}
                >
                  <Button size="small">设为{r.label}</Button>
                </Popconfirm>
              ))}
            </Space>
          )}
        />
      )}

      <Table<UserAdminRecord>
        rowKey="id"
        size="small"
        loading={listQuery.isLoading}
        dataSource={listQuery.data?.items ?? []}
        columns={columns}
        rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds }}
        pagination={{
          current: page,
          pageSize,
          total: listQuery.data?.total ?? 0,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 个用户`,
          onChange: (p) => setPage(p),
        }}
      />

      {/* 编辑弹窗（保存前二次确认在 handleEditSubmit 内） */}
      <Modal
        title={editing ? `编辑用户：${editing.username}` : ''}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={handleEditSubmit}
        okText="保存"
        cancelText="取消"
        confirmLoading={editMutation.isPending}
        destroyOnClose
      >
        <Form form={form} layout="vertical" size="small">
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 2, max: 150, message: '用户名 2-150 个字符' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="nickname" label="昵称">
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input placeholder="留空表示清空" />
          </Form.Item>
          <Form.Item name="phone" label="联系电话">
            <Input placeholder="选填" maxLength={32} />
          </Form.Item>
          <Form.Item name="role" label="角色（提权/降权）" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={roleOptions} />
          </Form.Item>
          <Form.Item name="is_active" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 单用户操作日志抽屉（权限变更历史追溯） */}
      <Drawer
        title={logTarget ? `操作日志：${logTarget.username}` : ''}
        open={!!logTarget}
        onClose={() => setLogTarget(null)}
        width={480}
      >
        {logsQuery.isLoading && <Text type="secondary">加载中…</Text>}
        {logsQuery.data && logsQuery.data.total === 0 && <Text type="secondary">暂无操作记录</Text>}
        {(logsQuery.data?.items ?? []).map(log => (
          <div key={log.id} style={{ borderBottom: '1px solid var(--cn-border)', padding: '8px 0' }}>
            <Space size={8}>
              <Tag color={log.action === 'role_change' ? 'orange' : log.action === 'deactivate' ? 'red' : 'blue'} style={{ marginRight: 0 }}>
                {ACTION_LABELS[log.action] ?? log.action}
              </Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {log.created_at ? new Date(log.created_at).toLocaleString() : ''}
              </Text>
            </Space>
            <div style={{ marginTop: 4 }}>
              <DiffSummary log={log} />
            </div>
          </div>
        ))}
      </Drawer>
    </div>
  )
}

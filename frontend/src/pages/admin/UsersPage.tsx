/** 用户管理页 — 用户列表 / 新建 / 编辑 / 批量操作 / 操作日志（权限变更历史）.
 *
 * 由 AdminPanel 以「用户管理」Tab 挂载，门控在 AdminPanel（仅系统管理员可见）。
 * 所有写操作经 modal.confirm 二次确认，变更由后端记录操作日志。
 */

import { useMemo, useState, type Key } from 'react'
import {
  Table, Button, Input, Select, Space, Tag, Modal, Form, Switch, Radio,
  App as AntApp, Typography, Drawer, Popconfirm, Checkbox, Empty, Pagination, Spin,
  Upload, Dropdown, Alert,
} from 'antd'
import type { UploadProps, MenuProps } from 'antd'
import { EditOutlined, PlusOutlined, ReloadOutlined, UploadOutlined, DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi } from '@/api'
import SearchInput from '@/components/SearchInput'
import { useResponsive } from '@/hooks/useResponsive'
import type {
  UserAdminRecord, UserRole, UserAuditLogRecord, BatchUserActionRequest, UserAdminUpdateRequest,
  UserImportResponse, UserImportRowResult, AdminRegisterRequest,
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
  import: '批量导入',
  export: '导出',
  password_reset: '重置密码',
}

/** 从 Content-Disposition 解析下载文件名（优先 RFC 5987 的 filename*，兼容中文） */
function filenameFromDisposition(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8?.[1]) {
    try { return decodeURIComponent(utf8[1]) } catch { /* 非法编码回退 */ }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(disposition)
  return ascii?.[1] ?? fallback
}

/** 触发浏览器下载 Blob */
function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // 延迟释放，避免部分浏览器下载中断
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** CSV 单元格公式注入防护（与表格导出同口径） */
function csvCell(value: string): string {
  return /^[=+\-@\t\r]/.test(value) ? `'${value}` : value
}

const IMPORT_STATUS_META: Record<string, { color: string; label: string }> = {
  ok: { color: 'green', label: '成功' },
  skipped: { color: 'orange', label: '跳过' },
  failed: { color: 'red', label: '失败' },
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
    total?: number
    created?: number
    skipped?: number
    count?: number
    format?: string
    usernames?: string[]
    generated?: boolean
    revoked_sessions?: number
  }
  if (log.action === 'password_reset') {
    return (
      <div style={{ fontSize: 12 }}>
        <div>{detail.generated ? '自动生成随机密码' : '管理员手工设定新密码'}</div>
        <div>已吊销 {detail.revoked_sessions ?? 0} 个会话</div>
      </div>
    )
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
  if (log.action === 'import') {
    return (
      <div style={{ fontSize: 12 }}>
        <div>
          共 {detail.total ?? 0} 行：成功 {detail.created ?? 0} / 跳过 {detail.skipped ?? 0} / 失败 {detail.failed ?? 0}
        </div>
        {(detail.usernames ?? []).length > 0 && <div>新建：{(detail.usernames ?? []).join('、')}</div>}
      </div>
    )
  }
  if (log.action === 'export') {
    return (
      <div style={{ fontSize: 12 }}>
        <div>导出 {detail.count ?? 0} 个用户（{String(detail.format ?? 'csv').toUpperCase()}）</div>
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

interface CreateFormValues {
  username: string
  nickname?: string
  email?: string
  role: UserRole
  password: string
}

export default function UsersPage() {
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<EditFormValues>()
  const [createForm] = Form.useForm<CreateFormValues>()

  // ── 列表筛选/分页状态 ──
  const [keyword, setKeyword] = useState('')
  const [roleFilter, setRoleFilter] = useState<UserRole | undefined>()
  const [activeFilter, setActiveFilter] = useState<boolean | undefined>()
  const [page, setPage] = useState(1)
  const pageSize = 20
  const [selectedIds, setSelectedIds] = useState<Key[]>([])

  // ── 新建弹窗 ──
  const [createOpen, setCreateOpen] = useState(false)

  // ── 编辑弹窗 ──
  const [editing, setEditing] = useState<UserAdminRecord | null>(null)

  // ── 重置密码弹窗（默认自动生成，可切手工输入；生成结果仅展示一次） ──
  const [resetTarget, setResetTarget] = useState<UserAdminRecord | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetMode, setResetMode] = useState<'auto' | 'manual'>('auto')
  const [resetResult, setResetResult] = useState<{ password: string; revoked: number } | null>(null)
  const [resetForm] = Form.useForm<{ new_password: string }>()

  // ── 日志抽屉（单用户） ──
  const [logTarget, setLogTarget] = useState<UserAdminRecord | null>(null)

  // ── 批量导入弹窗（选文件 → 预演 → 确认 → 结果） ──
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<UserImportResponse | null>(null)
  const [importResult, setImportResult] = useState<UserImportResponse | null>(null)

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

  const resetMutation = useMutation({
    mutationFn: ({ id, newPassword }: { id: number; newPassword?: string }) =>
      authApi.resetUserPassword(id, newPassword ? { new_password: newPassword } : {}),
    onSuccess: (res) => {
      invalidate()
      if (res.generated_password) {
        // 自动生成的密码只在本次响应出现，留在弹窗内一次性展示
        setResetResult({ password: res.generated_password, revoked: res.revoked_sessions })
      } else {
        setResetOpen(false)
        message.success(
          `密码已重置，目标用户需用新密码重新登录（已吊销 ${res.revoked_sessions} 个会话）`,
        )
      }
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '重置密码失败')
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: AdminRegisterRequest) => authApi.adminRegister(data),
    onSuccess: (user) => {
      message.success(`用户 ${user.username} 已创建`)
      setCreateOpen(false)
      createForm.resetFields()
      invalidate()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '创建失败')
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

  /** 导出：带上当前筛选条件，与列表口径一致 */
  const exportMutation = useMutation({
    mutationFn: (format: 'csv' | 'xlsx') =>
      authApi.exportUsers({
        format,
        keyword: keyword || undefined,
        role: roleFilter,
        is_active: activeFilter,
      }),
    onSuccess: (res, format) => {
      const disposition = res.headers['content-disposition'] as string | undefined
      downloadBlob(
        filenameFromDisposition(disposition, `用户列表.${format}`),
        res.data as Blob,
      )
      message.success(`已导出 ${listQuery.data?.total ?? 0} 个用户`)
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '导出失败')
    },
  })

  /** 预演：只校验不写库，返回可导入/跳过/失败明细 */
  const previewMutation = useMutation({
    mutationFn: (file: File) => authApi.importUsers(file, true),
    onSuccess: (data) => setImportPreview(data),
    onError: (err) => {
      setImportFile(null)
      message.error(err instanceof Error ? err.message : '解析文件失败')
    },
  })

  /** 正式导入：逐行创建，自动生成密码随结果返回一次 */
  const importMutation = useMutation({
    mutationFn: (file: File) => authApi.importUsers(file, false),
    onSuccess: (data) => {
      setImportResult(data)
      setImportPreview(null)
      const parts = [`成功 ${data.created} 个`]
      if (data.skipped) parts.push(`跳过 ${data.skipped} 个`)
      if (data.failed) parts.push(`失败 ${data.failed} 个`)
      message.success(`导入完成：${parts.join('，')}`)
      invalidate()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '导入失败')
    },
  })

  const openImport = () => {
    setImportFile(null)
    setImportPreview(null)
    setImportResult(null)
    setImportOpen(true)
  }

  const closeImport = () => {
    setImportOpen(false)
    setImportFile(null)
    setImportPreview(null)
    setImportResult(null)
  }

  const beforeUpload: UploadProps['beforeUpload'] = (file) => {
    setImportFile(file)
    setImportResult(null)
    setImportPreview(null)
    previewMutation.mutate(file)
    return false // 阻止 antd 自动上传，改为手动调用预演/导入接口
  }

  const exportMenu = useMemo<MenuProps>(() => ({
    items: [
      { key: 'csv', label: '导出 CSV' },
      { key: 'xlsx', label: '导出 Excel' },
    ],
    onClick: ({ key }) => exportMutation.mutate(key as 'csv' | 'xlsx'),
  }), [exportMutation])

  /** 初始密码只在本次导入结果中可见，提供一次性 CSV 下载 */
  const generatedPasswordRows = (importResult?.results ?? []).filter(r => r.generated_password)

  const downloadGeneratedPasswords = () => {
    if (generatedPasswordRows.length === 0) return
    const lines = [
      'username,password',
      ...generatedPasswordRows.map(r => `${csvCell(r.username ?? '')},${csvCell(r.generated_password ?? '')}`),
    ]
    downloadBlob(
      '用户初始密码.csv',
      new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }),
    )
    message.success('初始密码清单已下载，请尽快分发给用户并提醒修改密码')
  }

  const roleOptions = useMemo(
    () => ROLE_OPTIONS.map(r => ({ value: r.value, label: r.label })),
    [],
  )

  const openCreate = () => {
    createForm.resetFields()
    createForm.setFieldsValue({ role: 'user' })
    setCreateOpen(true)
  }

  /** 新建提交 —— 先做二次确认，确认后才调用后端 */
  const handleCreateSubmit = () => {
    createForm.validateFields().then((values) => {
      modal.confirm({
        title: '确认创建该用户？',
        content: (
          <div style={{ fontSize: 13 }}>
            <div>用户名：<Text strong>{values.username}</Text></div>
            <div>角色：{roleMeta(values.role).label}</div>
            {values.email ? <div>邮箱：{values.email}</div> : null}
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">初始密码请妥善保存并转交用户，建议其登录后尽快修改。</Text>
            </div>
          </div>
        ),
        okText: '确认创建',
        cancelText: '取消',
        onOk: () => createMutation.mutateAsync({
          username: values.username,
          nickname: values.nickname || '',
          email: values.email?.trim() || null,
          role: values.role,
          password: values.password,
        }),
      })
    })
  }

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

  const openReset = (record: UserAdminRecord) => {
    setResetTarget(record)
    setResetMode('auto')
    setResetResult(null)
    resetForm.resetFields()
    setResetOpen(true)
  }

  /** 重置密码提交 —— 默认自动生成；手工输入需二次确认（含会话失效提示） */
  const handleResetSubmit = () => {
    if (!resetTarget) return
    const run = (newPassword?: string) => {
      modal.confirm({
        title: `确认重置用户「${resetTarget.username}」的密码？`,
        content: (
          <div style={{ fontSize: 13 }}>
            <div>
              {newPassword
                ? '将使用你手工设定的新密码。'
                : '将由服务端生成 12 位随机密码，并仅在结果中展示一次。'}
            </div>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">重置后该用户全部会话立即失效，需用新密码重新登录；操作会记录到操作日志。</Text>
            </div>
          </div>
        ),
        okText: '确认重置',
        okType: 'danger',
        cancelText: '取消',
        onOk: () => resetMutation.mutateAsync({ id: resetTarget.id as number, newPassword }),
      })
    }
    if (resetMode === 'auto') {
      run()
      return
    }
    resetForm.validateFields().then(values => run(values.new_password)).catch(() => {
      // 校验失败时由 Form.Item 就地展示错误，无需额外提示
    })
  }

  const closeReset = () => {
    setResetOpen(false)
    setResetTarget(null)
    setResetResult(null)
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
      modal.confirm({
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
    modal.confirm({
      title,
      content: '操作将逐项执行并记录到操作日志；不能作用于当前登录用户与最后一个可用超管。',
      okText: '确认执行',
      okType: action === 'deactivate' ? 'danger' : 'primary',
      cancelText: '取消',
      onOk: () => batchMutation.mutateAsync({ action, user_ids: ids, role }),
    })
  }

  // 移动端：筛选控件整行排布，避免固定宽度在选择器里被挤压
  const { isMobile } = useResponsive()

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
      title: '操作', key: 'actions', width: 220,
      render: (_: unknown, record: UserAdminRecord) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button size="small" type="link" onClick={() => openReset(record)}>
            重置密码
          </Button>
          <Button size="small" type="link" onClick={() => setLogTarget(record)}>
            日志
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="cn-admin-section" data-testid="users-page">
      {/* 工具栏：检索与筛选在左、结果计数与刷新在右；窄屏整行堆叠 */}
      <div className="cn-toolbar">
        <SearchInput
          size="middle"
          placeholder="搜索用户名/邮箱/昵称…"
          style={{ width: isMobile ? '100%' : 220 }}
          onPressEnter={(e) => { setKeyword(e.currentTarget.value); setPage(1) }}
          onChange={(e) => { if (!e.target.value) { setKeyword(''); setPage(1) } }}
        />
        <Select
          placeholder="角色筛选"
          allowClear
          style={{ width: isMobile ? '100%' : 140 }}
          options={roleOptions}
          value={roleFilter}
          onChange={(v) => { setRoleFilter(v); setPage(1) }}
        />
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: isMobile ? '100%' : 120 }}
          options={[
            { value: 'true', label: '启用' },
            { value: 'false', label: '禁用' },
          ]}
          value={activeFilter === undefined ? undefined : String(activeFilter)}
          onChange={(v) => { setActiveFilter(v === undefined ? undefined : v === 'true'); setPage(1) }}
        />
        <div className="cn-toolbar-end">
          <span className="cn-record-pill">{listQuery.data?.total ?? 0} 个账号</span>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
          <Button icon={<UploadOutlined />} onClick={openImport}>导入</Button>
          <Dropdown menu={exportMenu} trigger={['click']}>
            <Button icon={<DownloadOutlined />} loading={exportMutation.isPending}>导出</Button>
          </Dropdown>
          <Button icon={<ReloadOutlined />} onClick={() => invalidate()}>刷新</Button>
        </div>
      </div>

      {selectedIds.length > 0 && (
        <div className="cn-selection-bar" data-testid="users-selection-bar">
          <span className="cn-selection-count">已选择 {selectedIds.length} 个用户：</span>
          <Space wrap size={8}>
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
        </div>
      )}

      {isMobile ? (
        /* 窄屏卡片列表：8 列表格需左右滑动才能看到角色/状态/操作，卡片一屏一实体、操作直接可见 */
        <Spin spinning={listQuery.isLoading}>
          {(listQuery.data?.items ?? []).length === 0 ? (
            <Empty description="暂无用户" className="cn-state" data-testid="users-mobile-empty" />
          ) : (
            <div className="cn-user-cards" data-testid="users-mobile-list">
              {(listQuery.data?.items ?? []).map(u => (
                <div key={u.id} className="cn-user-card" data-testid={`user-card-${u.id}`}>
                  {/* 身份信息独占整行（窄屏不与标签争宽度，邮箱/昵称不再被截断） */}
                  <div className="cn-user-card-main">
                    <Checkbox
                      checked={selectedIds.some(id => String(id) === String(u.id))}
                      onChange={e => setSelectedIds(prev =>
                        e.target.checked
                          ? [...prev, u.id]
                          : prev.filter(id => String(id) !== String(u.id)))}
                      aria-label={`选择用户 ${u.username}`}
                    />
                    <div className="cn-user-card-identity">
                      <div className="cn-user-card-name" title={u.username}>
                        {u.username}
                        {u.nickname && <span className="cn-user-card-nickname">（{u.nickname}）</span>}
                      </div>
                      <div className="cn-user-card-meta" title={u.email ?? undefined}>{u.email ?? '未填邮箱'}</div>
                      {u.phone && <div className="cn-user-card-meta">{u.phone}</div>}
                    </div>
                    {u.is_active
                      ? <Tag color="green" style={{ marginInlineEnd: 0 }}>启用</Tag>
                      : <Tag color="default" style={{ marginInlineEnd: 0 }}>禁用</Tag>}
                  </div>
                  <div className="cn-user-card-actions">
                    <Space size={4} wrap>
                      <Tag color={roleMeta(u.role).color} style={{ marginInlineEnd: 0 }}>{roleMeta(u.role).label}</Tag>
                      {u.is_superuser && <Tag color="purple" style={{ marginInlineEnd: 0 }}>超管</Tag>}
                    </Space>
                    <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                      <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(u)}>编辑</Button>
                      <Button size="small" type="link" onClick={() => openReset(u)}>重置密码</Button>
                      <Button size="small" type="link" onClick={() => setLogTarget(u)}>日志</Button>
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
          <Pagination
            style={{ marginTop: 'var(--cn-space-lg)', textAlign: 'center' }}
            current={page}
            pageSize={pageSize}
            total={listQuery.data?.total ?? 0}
            showSizeChanger={false}
            showTotal={t => `共 ${t} 个用户`}
            onChange={p => setPage(p)}
          />
        </Spin>
      ) : (
        <div className="cn-grid-card" data-testid="users-table-card">
          <Table<UserAdminRecord>
            className="cn-table-list"
            rowKey="id"
            size="small"
            loading={listQuery.isLoading}
            dataSource={listQuery.data?.items ?? []}
            columns={columns}
            // 窄屏列宽不压缩（否则「昵称」「邮箱」会逐字换行/被裁切），改为表格横向滚动
            scroll={{ x: 'max-content' }}
            rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds }}
            locale={{ emptyText: <Empty description="暂无用户" /> }}
            pagination={{
              current: page,
              pageSize,
              total: listQuery.data?.total ?? 0,
              showSizeChanger: false,
              showTotal: (t) => `共 ${t} 个用户`,
              onChange: (p) => setPage(p),
            }}
          />
        </div>
      )}

      {/* 重置密码弹窗：默认自动生成一次性密码，可切手工输入 */}
      <Modal
        title="重置用户密码"
        open={resetOpen}
        onCancel={closeReset}
        width={520}
        destroyOnHidden
        footer={
          resetResult
            ? [<Button key="close" type="primary" onClick={closeReset}>我已保存，关闭</Button>]
            : [
              <Button key="cancel" onClick={closeReset}>取消</Button>,
              <Button
                key="submit"
                type="primary"
                danger
                loading={resetMutation.isPending}
                onClick={handleResetSubmit}
              >
                {resetMode === 'auto' ? '生成并重置' : '确认重置'}
              </Button>,
            ]
        }
      >
        {resetTarget && (
          <div style={{ marginBottom: 12, fontSize: 13 }}>
            目标用户：<Text strong>{resetTarget.username}</Text>
            {resetTarget.nickname ? `（${resetTarget.nickname}）` : ''}
            <div>
              <Text type="secondary">重置后该用户全部会话失效，需用新密码重新登录；不能重置自己的密码。</Text>
            </div>
          </div>
        )}
        {resetResult ? (
          <div data-testid="reset-password-result">
            <Alert
              type="success"
              showIcon
              style={{ marginBottom: 12 }}
              message="密码已重置"
              description={`已吊销 ${resetResult.revoked} 个会话。以下密码只展示这一次，请立即转交用户。`}
            />
            <Typography.Paragraph copyable={{ text: resetResult.password }} style={{ marginBottom: 0 }}>
              <Text code>{resetResult.password}</Text>
            </Typography.Paragraph>
          </div>
        ) : (
          <Form form={resetForm} layout="vertical">
            <Form.Item label="新密码来源">
              <Radio.Group
                value={resetMode}
                onChange={e => setResetMode(e.target.value as 'auto' | 'manual')}
                options={[
                  { value: 'auto', label: '自动生成（推荐）' },
                  { value: 'manual', label: '手工输入' },
                ]}
              />
            </Form.Item>
            {resetMode === 'manual' && (
              <Form.Item
                name="new_password"
                label="新密码"
                rules={[
                  { required: true, message: '请输入新密码' },
                  { min: 6, max: 128, message: '密码长度须为 6-128 位' },
                ]}
              >
                <Input.Password placeholder="6-128 位" autoComplete="new-password" />
              </Form.Item>
            )}
          </Form>
        )}
      </Modal>

      {/* 批量导入弹窗：选文件 → 预演明细 → 确认导入 → 结果 + 初始密码下载 */}
      <Modal
        title="批量导入用户"
        open={importOpen}
        onCancel={closeImport}
        width={720}
        destroyOnHidden
        footer={
          importResult ? [
            <Button key="close" type="primary" onClick={closeImport}>关闭</Button>,
          ] : [
            <Button key="cancel" onClick={closeImport}>取消</Button>,
            <Button
              key="submit"
              type="primary"
              disabled={!importFile || !importPreview || importPreview.created === 0}
              loading={importMutation.isPending}
              onClick={() => importFile && importMutation.mutate(importFile)}
            >
              确认导入{importPreview ? ` ${importPreview.created} 个用户` : ''}
            </Button>,
          ]
        }
      >
        {!importPreview && !importResult && (
          <>
            <Upload.Dragger
              accept=".csv,.tsv,.xlsx,.xlsm"
              beforeUpload={beforeUpload}
              showUploadList={false}
              disabled={previewMutation.isPending}
            >
              <div className="ant-upload-drag-icon">
                {previewMutation.isPending ? <Spin /> : <InboxOutlined />}
              </div>
              <p className="ant-upload-text">点击或拖拽文件到此处</p>
              <p className="ant-upload-hint">
                {previewMutation.isPending ? '正在解析文件…' : '支持 CSV / Excel（.xlsx），单次最多 1000 行'}
              </p>
            </Upload.Dragger>
            <div style={{ marginTop: 12, fontSize: 12 }}>
              <Text type="secondary">
                列头：username（用户名，必填）、email（邮箱）、phone（电话）、nickname（昵称）、
                role（角色）、is_active（启用状态）、password（初始密码）。
                密码留空将自动生成 12 位，仅在导入结果中展示一次；已存在的用户名/邮箱会跳过且不修改。
              </Text>
            </div>
          </>
        )}

        {(importPreview || importResult) && (
          <>
            <Alert
              type={importResult && importResult.failed > 0 ? 'warning' : 'info'}
              showIcon
              message={
                importResult
                  ? `共 ${importResult.total} 行：成功 ${importResult.created}，跳过 ${importResult.skipped}，失败 ${importResult.failed}`
                  : `预演结果：共 ${importPreview!.total} 行，可导入 ${importPreview!.created}，跳过 ${importPreview!.skipped}，失败 ${importPreview!.failed}`
              }
              description={
                importResult
                  ? '导入已完成。生成的初始密码只在本次结果中可见，关闭后无法再次查看。'
                  : '预演未写入数据库。确认后将逐行创建用户，已存在的用户名/邮箱会被跳过。'
              }
              action={
                importResult && generatedPasswordRows.length > 0 ? (
                  <Button size="small" type="primary" onClick={downloadGeneratedPasswords}>
                    下载初始密码（{generatedPasswordRows.length}）
                  </Button>
                ) : undefined
              }
            />
            <Table<UserImportRowResult>
              style={{ marginTop: 12 }}
              size="small"
              rowKey="row_index"
              dataSource={(importResult ?? importPreview)?.results ?? []}
              pagination={{ pageSize: 10, size: 'small', hideOnSinglePage: true }}
              columns={[
                { title: '行号', dataIndex: 'row_index', width: 60 },
                { title: '用户名', dataIndex: 'username', width: 160, render: (v: string | null) => v ?? '—' },
                {
                  title: '状态', dataIndex: 'status', width: 90,
                  render: (status: string) => {
                    const meta = IMPORT_STATUS_META[status] ?? IMPORT_STATUS_META.failed
                    const label = status === 'ok' && !importResult ? '可导入' : meta.label
                    return <Tag color={meta.color} style={{ marginRight: 0 }}>{label}</Tag>
                  },
                },
                {
                  title: '说明', dataIndex: 'message',
                  render: (message: string, row: UserImportRowResult) =>
                    message || (row.generated_password ? '已生成初始密码' : '—'),
                },
              ]}
            />
          </>
        )}
      </Modal>

      {/* 新建弹窗（保存前二次确认在 handleCreateSubmit 内） */}
      <Modal
        title="新建用户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreateSubmit}
        okText="创建"
        cancelText="取消"
        confirmLoading={createMutation.isPending}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" size="small">
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, min: 2, max: 150, message: '用户名 2-150 个字符' }]}
          >
            <Input placeholder="登录名，全库唯一" />
          </Form.Item>
          <Form.Item name="nickname" label="昵称">
            <Input placeholder="留空则使用角色中文名" />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={roleOptions} />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[{ required: true, min: 6, max: 128, message: '密码 6-128 位' }]}
          >
            <Input.Password placeholder="至少 6 位" autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑弹窗（保存前二次确认在 handleEditSubmit 内） */}
      <Modal
        title={editing ? `编辑用户：${editing.username}` : ''}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={handleEditSubmit}
        okText="保存"
        cancelText="取消"
        confirmLoading={editMutation.isPending}
        destroyOnHidden
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

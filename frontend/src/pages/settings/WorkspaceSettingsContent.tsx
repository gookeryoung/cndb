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
  Popconfirm, Divider, Card, Space, Avatar, Progress,
} from 'antd'
import { App as AntApp } from 'antd'
import {
  SettingOutlined, BarChartOutlined,
  FileTextOutlined, EyeOutlined, HddOutlined,
  ColumnWidthOutlined, UserOutlined, DeleteOutlined, SafetyOutlined, SwapOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceApi } from '@/api'
import type {
  WorkspaceDetail, WorkspaceMember, WorkspaceRole, WorkspaceType, WorkspaceVisibility,
  MemberUserBrief,
} from '@/api'
import { useAuthStore } from '@/store'
import HelpTip from '@/components/HelpTip'
import { formatSize } from '@/utils/formatSize'
import { WORKSPACE_TYPE_HINT, WORKSPACE_TYPE_LABEL, WORKSPACE_TYPE_OPTIONS } from '@/utils/workspaceType'
import AddMemberModal from './AddMemberModal'
import MemberZones from './MemberZones'
import TransferOwnerModal from './TransferOwnerModal'
import { ROLE_LABEL, VISIBILITY_LABEL, getAssignableRoles } from './workspaceRoles'

interface Props {
  wid: string
  initialTab?: 'basic' | 'permissions' | 'stats'
  /** 设置保存后通知工作区列表刷新 */
  onUpdated?: () => void
  /** 删除工作区成功后回调（Modal 模式下用于关闭弹窗，回到工作区列表视图） */
  onDeleted?: () => void
}


export default function WorkspaceSettingsContent({
  wid, initialTab = 'basic', onUpdated, onDeleted,
}: Props) {
  const queryClient = useQueryClient()
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const currentUser = useAuthStore(s => s.user)
  const [form] = Form.useForm()
  const [activeTab, setActiveTab] = useState(initialTab)
  const [candidatesSearch, setCandidatesSearch] = useState('')
  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [addMemberUsername, setAddMemberUsername] = useState<string | null>(null)
  const [addMemberRole, setAddMemberRole] = useState<WorkspaceRole>('editor')
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferTargetId, setTransferTargetId] = useState<string | null>(null)

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

  // 候选用户（添加成员时搜索）
  const { data: candidatesData = [] as MemberUserBrief[], isLoading: candidatesLoading } = useQuery<MemberUserBrief[]>({
    queryKey: ['workspace-member-candidates', wid, candidatesSearch],
    queryFn: async () => {
      const res = await workspaceApi.memberCandidates(wid, candidatesSearch)
      return res.results
    },
    enabled: !!wid && detail?.current_user_role === 'owner',
    gcTime: 0,
  })

  // 打开/切换时重置 Tab + 填充表单
  useEffect(() => {
    setActiveTab(initialTab)
    setCandidatesSearch('')
    setAddMemberUsername(null)
    setAddMemberRole('editor')
  }, [initialTab, wid])

  useEffect(() => {
    if (detail) {
      form.setFieldsValue({
        name: detail.name,
        description: detail.description,
        visibility: detail.visibility ?? 'member',
        workspace_type: detail.workspace_type ?? 'data_doc',
        tags: (detail.tags ?? []).join(', '),
      })
    }
  }, [detail, form])

  // 当前用户角色
  const myRole = detail?.current_user_role ?? null

  // 权限判断 —— 三级角色：管理操作收敛为 owner
  const canEditBasic = myRole === 'owner'
  const canManageMembers = myRole === 'owner'
  const canDeleteWorkspace = myRole === 'owner'
  const assignableRoles = useMemo(() => getAssignableRoles(myRole), [myRole])

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
        workspace_type: v.workspace_type as WorkspaceType,
        tags: tagsStr.split(/[,，]/).map(s => s.trim()).filter(Boolean),
      })
    },
    onSuccess: () => {
      message.success('设置已保存')
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      onUpdated?.()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存设置失败'),
  })

  const toggleAllowEdit = useMutation({
    mutationFn: (allowEdit: boolean) =>
      workspaceApi.update(wid, { allow_edit: allowEdit }),
    onSuccess: () => {
      message.success('编辑权限已更新')
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新编辑权限失败'),
  })

  const addMember = useMutation({
    mutationFn: ({ username, role }: { username: string; role: string }) =>
      workspaceApi.addMember(wid, username, role),
    onSuccess: () => {
      message.success('已添加成员')
      setCandidatesSearch('')
      setAddMemberUsername(null)
      setAddMemberOpen(false)
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '添加成员失败'),
  })

  const changeRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: number | string; role: string }) =>
      workspaceApi.updateMemberRole(wid, memberId, role),
    onSuccess: () => {
      message.success('角色已更新')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新角色失败'),
  })

  const kick = useMutation({
    mutationFn: (memberId: number | string) => workspaceApi.removeMember(wid, memberId),
    onSuccess: () => {
      message.success('已移除成员')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '移除成员失败'),
  })

  const removeWs = useMutation({
    mutationFn: () => workspaceApi.remove(wid),
    onSuccess: () => {
      message.success('工作区已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      // Modal 模式下先关闭弹窗露出工作区列表，再执行独立页面模式的跳转
      onDeleted?.()
      // 删除工作区后统一回到工作区列表（无论嵌入在独立页面还是 Modal）
      navigate('/w', { replace: true })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除工作区失败'),
  })

  const transferOwner = useMutation({
    mutationFn: (userId: number) => workspaceApi.transferOwner(wid, userId),
    onSuccess: () => {
      message.success('所有权已转让')
      queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
      queryClient.invalidateQueries({ queryKey: ['workspace-members', wid] })
      setTransferOpen(false)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '转让失败'),
  })

  const statItems = useMemo(() => {
    if (!detail) return []
    return [
      { label: '数据表', value: (detail.table_count ?? 0).toLocaleString(), icon: <FileTextOutlined />, color: 'var(--cn-brand-color)' },
      { label: '成员', value: (detail.member_count ?? 0).toLocaleString(), icon: <UserOutlined />, color: '#8b5cf6' },
      { label: '视图', value: (detail.view_count ?? 0).toLocaleString(), icon: <EyeOutlined />, color: '#10b981' },
      { label: '数据行', value: (detail.total_rows ?? 0).toLocaleString(), icon: <ColumnWidthOutlined />, color: '#f59e0b' },
      { label: '占用空间', value: formatSize(detail.storage_bytes ?? 0), icon: <HddOutlined />, color: '#0ea5e9' },
    ]
  }, [detail])

  // 存储用量：已用 / 配额（默认 100MB）与使用率配色
  const storageUsed = detail?.storage_bytes ?? 0
  const storageQuota = detail?.storage_quota_bytes ?? 100 * 1024 * 1024
  const storagePercent = storageQuota > 0
    ? Math.min(100, (storageUsed / storageQuota) * 100)
    : 100
  const storageColor = storagePercent >= 100 ? '#dc2626' : storagePercent >= 80 ? '#f59e0b' : '#0ea5e9'

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
  // 权限 Tab 内部组件
  const membersTabChildren = (
    <div>
      {/* ── Owner Card ── */}
      <Card
        size="small"
        title={<Space><SafetyOutlined /> 工作区所有者</Space>}
        style={{ marginBottom: 12 }}
        extra={
          myRole === 'owner' ? (
            <Button
              size="small"
              icon={<SwapOutlined />}
              onClick={() => setTransferOpen(true)}
            >
              转让所有权
            </Button>
          ) : null
        }
      >
        {detail?.owner ? (
          <Space>
            <Avatar icon={<UserOutlined />} />
            <div>
              <div style={{ fontWeight: 500 }}>
                {detail.owner.username}
                {detail.owner.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8, fontSize: 13 }}>({detail.owner.nickname})</span>}
                {myRole === 'owner' && <Tag color="blue" style={{ marginLeft: 8 }}>就是您</Tag>}
              </div>
              <div style={{ fontSize: 12, color: 'var(--cn-text-muted)' }}>
                所有者对工作区负全责，可管理成员与转让所有权
              </div>
            </div>
          </Space>
        ) : (
          <div style={{ color: 'var(--cn-text-muted)' }}>未指定所有者</div>
        )}
      </Card>

      {/* ── 编辑权限开关（allow_edit） ── */}
      <Card
        size="small"
        title={<Space><EyeOutlined /> 编辑权限</Space>}
        style={{ marginBottom: 12 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Switch
            checked={detail?.allow_edit ?? true}
            disabled={!canEditBasic}
            onChange={(checked) => toggleAllowEdit.mutate(checked)}
            loading={toggleAllowEdit.isPending}
          />
          <span style={{ color: 'var(--cn-text-secondary)', fontSize: 13 }}>
            {detail?.allow_edit ?? true
              ? '已开启：编辑者可以修改数据'
              : '已关闭：仅所有者可以修改数据，其他成员只能查看'}
          </span>
        </div>
      </Card>

      {!canManageMembers && (
        <div style={{ marginBottom: 12, padding: 10, ...warningBoxStyle, color: '#92400e', fontSize: 13 }}>
          仅所有者可管理成员与权限
        </div>
      )}

      {/* ── 编辑者区 / 查看者区（三区布局） ── */}
      <MemberZones
        members={members}
        membersLoading={membersLoading}
        canManageMembers={canManageMembers}
        currentMemberId={currentMemberId}
        assignableRoles={assignableRoles}
        onRoleChange={(memberId, role) => changeRole.mutate({ memberId, role })}
        onKick={memberId => kick.mutate(memberId)}
        onAddMember={role => {
          setAddMemberUsername(null)
          setAddMemberRole(role)
          setCandidatesSearch('')
          setAddMemberOpen(true)
        }}
      />

      {/* ── 添加成员 Modal ── */}
      <AddMemberModal
        open={addMemberOpen}
        onCancel={() => setAddMemberOpen(false)}
        onSubmit={() => {
          if (addMemberUsername) addMember.mutate({ username: addMemberUsername, role: addMemberRole })
        }}
        username={addMemberUsername}
        onUsernameChange={setAddMemberUsername}
        role={addMemberRole}
        onRoleChange={setAddMemberRole}
        candidates={candidatesData}
        candidatesLoading={candidatesLoading}
        candidatesSearch={candidatesSearch}
        onSearch={setCandidatesSearch}
        assignableRoles={assignableRoles}
        submitting={addMember.isPending}
      />

      {/* ── 转让所有权 Modal ── */}
      <TransferOwnerModal
        open={transferOpen}
        onCancel={() => setTransferOpen(false)}
        onOk={() => {
          const selected = members.find(m => m.role !== 'owner' && String(m.user.id) === String(transferTargetId))
          if (selected) transferOwner.mutate(Number(selected.user.id))
        }}
        options={members
          .filter(m => m.role !== 'owner')
          .map(m => ({
            value: String(m.user.id),
            label: `${m.user.username}${m.user.nickname ? ` (${m.user.nickname})` : ''}`,
          }))}
        value={transferTargetId}
        onChange={setTransferTargetId}
        confirming={transferOwner.isPending}
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
          initialValues={{ visibility: 'member', tags: '', workspace_type: 'data_doc' }}
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
          <Form.Item
            name="workspace_type"
            label={<>工作区类型<HelpTip title="决定工作区开放的功能：数据 + 文档=全部功能；数据=仅数据表与数据分析；文档=仅文档。修改后顶部页签与导航随之调整" /></>}
          >
            <Select
              options={WORKSPACE_TYPE_OPTIONS.map(o => ({ ...o, label: `${o.label}（${WORKSPACE_TYPE_HINT[o.value]}）` }))}
              disabled={!canEditBasic}
            />
          </Form.Item>
          <Form.Item
            name="visibility"
            label={<>公开性<HelpTip title="修改后立即生效：公开=任何人可读；成员可见=仅工作区成员可访问；私有=仅所有者可见" /></>}
          >
            <Select
              options={Object.entries(VISIBILITY_LABEL).map(([v, l]) => ({ value: v, label: l }))}
              disabled={!canEditBasic}
            />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）">
            <Input placeholder="例如：研发, 产品, 核心业务" />
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
      key: 'permissions',
      label: <span><SafetyOutlined /> 权限</span>,
      children: membersTabChildren,
    },
    {
      key: 'stats',
      label: <span><BarChartOutlined /> 统计信息</span>,
      children: (
        <div>
          {/* 统计卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 16 }}>
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
                  {item.value}
                </div>
              </div>
            ))}
          </div>

          {/* 存储用量：已用 / 配额 + 使用率进度条 */}
          <div style={{ padding: 16, ...subtleBoxStyle, marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--cn-text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                <HddOutlined /> 存储用量
              </span>
              <span style={{ fontSize: 13, color: 'var(--cn-text-secondary)' }}>
                {formatSize(storageUsed)} / {formatSize(storageQuota)}
              </span>
            </div>
            <Progress percent={Math.round(storagePercent * 10) / 10} strokeColor={storageColor} size="small" />
            <div style={{ fontSize: 12, color: 'var(--cn-text-muted)', marginTop: 4 }}>
              {storagePercent >= 100
                ? '存储空间已用尽，请清理文件或联系管理员扩容'
                : storagePercent >= 80
                  ? '存储空间即将用尽，建议清理或扩容'
                  : '可继续上传附件与保存文档'}
            </div>
          </div>

          {/* 当前角色 + 拥有者 */}
          <Descriptions title="角色信息" size="small" bordered column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="您的角色">
              {myRole
                ? <Tag color={myRole === 'owner' ? 'gold' : 'default'}>{ROLE_LABEL[myRole]}</Tag>
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
            <Descriptions.Item label="工作区类型">
              {WORKSPACE_TYPE_LABEL[detail?.workspace_type ?? 'data_doc']}
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

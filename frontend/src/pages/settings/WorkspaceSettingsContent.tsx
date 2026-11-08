/** 工作区设置 — 内容组件（可嵌入 Modal 或独立页面）.
 *
 * 包含三个分项：基本设置（含工作区概览统计）/ 权限 / 生命周期
 * 基本设置采用「顶部概览 + 左表单 / 右侧信息」布局：概览先行、可编辑项居中、只读与危险操作收敛到侧列。
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
  Popconfirm, Card, Space, Avatar, Progress,
} from 'antd'
import { App as AntApp } from 'antd'
import {
  FileTextOutlined, EyeOutlined, HddOutlined,
  ColumnWidthOutlined, UserOutlined, DeleteOutlined, SafetyOutlined, SwapOutlined,
  ReadOutlined, ToolOutlined, SettingOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { workspaceApi } from '@/api'
import type {
  WorkspaceDetail, WorkspaceMember, WorkspaceRole, WorkspaceVisibility,
  MemberUserBrief,
} from '@/api'
import { useAuthStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'
import HelpTip from '@/components/HelpTip'
import ModuleCheckCards from '@/components/ModuleCheckCards'
import { formatSize } from '@/utils/formatSize'
import {
  DEFAULT_WORKSPACE_MODULES, WORKSPACE_MODULE_LABEL, normalizeModules, workspaceModulesFeatures,
} from '@/utils/workspaceModules'
import AddMemberModal from './AddMemberModal'
import WorkspaceLifecyclePanel from './WorkspaceLifecyclePanel'
import MemberZones from './MemberZones'
import TransferOwnerModal from './TransferOwnerModal'
import { ROLE_LABEL, VISIBILITY_LABEL, getAssignableRoles } from './workspaceRoles'
import {
  WORKSPACE_SETTINGS_SECTIONS,
  type WorkspaceSettingsSectionKey,
} from './workspaceSettingsSections'
import { WEIGHT } from '@/theme/tokens'

interface Props {
  wid: string
  initialTab?: WorkspaceSettingsSectionKey
  /** 受控分项：独立页面由侧栏驱动时传入，此时不再渲染页内 Tabs */
  section?: WorkspaceSettingsSectionKey
  /** 设置保存后通知工作区列表刷新 */
  onUpdated?: () => void
  /** 删除工作区成功后回调（Modal 模式下用于关闭弹窗，回到工作区列表视图） */
  onDeleted?: () => void
}


export default function WorkspaceSettingsContent({
  wid, initialTab = 'basic', section, onUpdated, onDeleted,
}: Props) {
  const queryClient = useQueryClient()
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const currentUser = useAuthStore(s => s.user)
  const { isMobile } = useResponsive()
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
        modules: normalizeModules(detail.modules),
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
        modules: normalizeModules(v.modules),
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
    const features = workspaceModulesFeatures(detail.modules)
    return [
      ...(features.tables
        ? [
            { label: '数据表', value: (detail.table_count ?? 0).toLocaleString(), icon: <FileTextOutlined />, color: 'var(--cn-brand-color)' },
            { label: '视图', value: (detail.view_count ?? 0).toLocaleString(), icon: <EyeOutlined />, color: '#10b981' },
            { label: '数据行', value: (detail.total_rows ?? 0).toLocaleString(), icon: <ColumnWidthOutlined />, color: '#f59e0b' },
          ]
        : []),
      ...(features.documents
        ? [{ label: '文档', value: (detail.document_count ?? 0).toLocaleString(), icon: <ReadOutlined />, color: '#08979c' }]
        : []),
      ...(features.design
        ? [{ label: '设计', value: (detail.design_count ?? 0).toLocaleString(), icon: <ToolOutlined />, color: '#7c3aed' }]
        : []),
      { label: '成员', value: (detail.member_count ?? 0).toLocaleString(), icon: <UserOutlined />, color: '#8b5cf6' },
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
              <div style={{ fontWeight: WEIGHT.medium }}>
                {detail.owner.username}
                {detail.owner.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8, fontSize: 'var(--cn-text-sm)' }}>({detail.owner.nickname})</span>}
                {myRole === 'owner' && <Tag color="blue" style={{ marginLeft: 8 }}>就是您</Tag>}
              </div>
              <div style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-muted)' }}>
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
          <span style={{ color: 'var(--cn-text-secondary)', fontSize: 'var(--cn-text-sm)' }}>
            {detail?.allow_edit ?? true
              ? '已开启：编辑者可以修改数据'
              : '已关闭：仅所有者可以修改数据，其他成员只能查看'}
          </span>
        </div>
      </Card>

      {!canManageMembers && (
        <div style={{ marginBottom: 12, padding: 10, ...warningBoxStyle, color: '#92400e', fontSize: 'var(--cn-text-sm)' }}>
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
  // Tab 定义（文案 / 图标与侧栏共用 WORKSPACE_SETTINGS_SECTIONS）
  const tabLabel = (key: WorkspaceSettingsSectionKey) => {
    const meta = WORKSPACE_SETTINGS_SECTIONS.find(s => s.key === key)!
    return <span>{meta.icon} {meta.label}</span>
  }
  const tabs = [
    {
      key: 'basic',
      label: tabLabel('basic'),
      children: (
        <div className="cn-ws-basic-settings">
          {/* 概览统计（原「统计信息」分项并入基本设置）：先给全貌，再进入可编辑项 */}
          <div
            data-testid="ws-stats-grid"
            className="cn-ws-settings-stats"
            style={{
              gridTemplateColumns: isMobile ? 'repeat(2, minmax(0, 1fr))' : 'repeat(auto-fit, minmax(140px, 1fr))',
            }}
          >
            {statItems.map(item => (
              <div
                key={item.label}
                className="cn-ws-settings-stat"
                style={{ borderLeft: `3px solid ${item.color}` }}
              >
                <div className="cn-ws-settings-stat-label">{item.icon} {item.label}</div>
                <div className="cn-ws-settings-stat-value">{item.value}</div>
              </div>
            ))}
          </div>

          <div className="cn-ws-settings-layout">
            {/* 主列：可编辑的基本信息 */}
            <div className="cn-ws-settings-main">
              <Form
                form={form}
                layout="vertical"
                initialValues={{ visibility: 'member', tags: '', modules: [...DEFAULT_WORKSPACE_MODULES] }}
                onFinish={(v) => save.mutate(v)}
                disabled={!canEditBasic}
              >
                <Card size="small" title={<Space><SettingOutlined /> 基本信息</Space>}>
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
                  <Form.Item
                    name="modules"
                    label={<>功能模块<HelpTip title="勾选工作区开放的功能：数据分析与数据同步随数据表一并启用，质量检查恒可用。修改后顶部页签与导航随之调整" /></>}
                  >
                    <ModuleCheckCards disabled={!canEditBasic} />
                  </Form.Item>
                  {!canEditBasic && (
                    <div style={{ marginTop: 12, color: '#f59e0b', fontSize: 'var(--cn-text-sm)' }}>
                      ℹ️ 您的角色（{ROLE_LABEL[myRole ?? 'viewer']}）仅能查看设置，无法修改
                    </div>
                  )}
                </Card>

                {canEditBasic && (
                  <div className="cn-ws-settings-actions">
                    <Button
                      type="primary"
                      block={isMobile}
                      onClick={() => form.submit()}
                      loading={save.isPending}
                    >保存设置</Button>
                  </div>
                )}
              </Form>
            </div>

            {/* 侧列：存储 / 角色与只读信息 / 危险操作 */}
            <aside className="cn-ws-settings-side">
              <Card size="small" title={<Space><HddOutlined /> 存储用量</Space>}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 'var(--cn-text-sm)', color: 'var(--cn-text-secondary)' }}>已用 / 配额</span>
                  <span style={{ fontSize: 'var(--cn-text-sm)', color: 'var(--cn-text-secondary)' }}>
                    {formatSize(storageUsed)} / {formatSize(storageQuota)}
                  </span>
                </div>
                <Progress percent={Math.round(storagePercent * 10) / 10} strokeColor={storageColor} size="small" />
                <div style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-muted)', marginTop: 4 }}>
                  {storagePercent >= 100
                    ? '存储空间已用尽，请清理文件或联系管理员扩容'
                    : storagePercent >= 80
                      ? '存储空间即将用尽，建议清理或扩容'
                      : '可继续上传附件与保存文档'}
                </div>
              </Card>

              <Card size="small" title={<Space><UserOutlined /> 角色信息</Space>}>
                <Descriptions size="small" column={1} colon={false}>
                  <Descriptions.Item label="您的角色">
                    {myRole
                      ? <Tag color={myRole === 'owner' ? 'gold' : 'default'}>{ROLE_LABEL[myRole]}</Tag>
                      : <Tag>非成员</Tag>}
                  </Descriptions.Item>
                  <Descriptions.Item label="拥有者">
                    {detail?.owner
                      ? (
                        <>
                          {detail.owner.username}
                          {detail.owner.nickname && <span style={{ color: 'var(--cn-text-muted)', marginLeft: 8 }}>({detail.owner.nickname})</span>}
                        </>
                      )
                      : '未指定所有者'}
                  </Descriptions.Item>
                </Descriptions>
              </Card>

              <Card size="small" title="工作区信息（只读）">
                <Descriptions size="small" column={1} colon={false}>
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
                  <Descriptions.Item label="功能模块">
                    {normalizeModules(detail?.modules).map(m => (
                      <Tag key={m} style={{ marginInlineEnd: 4 }}>{WORKSPACE_MODULE_LABEL[m]}</Tag>
                    ))}
                  </Descriptions.Item>
                  <Descriptions.Item label="标签">
                    {(detail?.tags ?? []).length > 0
                      ? (detail?.tags ?? []).map(t => <Tag key={t}>{t}</Tag>)
                      : <span style={{ color: 'var(--cn-text-muted)' }}>暂无标签</span>}
                  </Descriptions.Item>
                </Descriptions>
              </Card>

              {/* 危险操作区 — 仅 owner 可见 */}
              {canDeleteWorkspace && (
                <div className="cn-ws-settings-danger" style={dangerBoxStyle}>
                  <div style={{ fontWeight: WEIGHT.semibold, color: '#dc2626', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <DeleteOutlined /> 危险操作
                  </div>
                  <div style={{ color: '#991b1b', fontSize: 'var(--cn-text-sm)', marginBottom: 12 }}>
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
                    <Button danger icon={<DeleteOutlined />} loading={removeWs.isPending} block={isMobile}>
                      删除工作区
                    </Button>
                  </Popconfirm>
                </div>
              )}
            </aside>
          </div>
        </div>
      ),
    },
    {
      key: 'permissions',
      label: tabLabel('permissions'),
      children: membersTabChildren,
    },
    {
      key: 'lifecycle',
      label: tabLabel('lifecycle'),
      children: (
        <WorkspaceLifecyclePanel
          wid={wid}
          canAdvance={myRole === 'owner' || myRole === 'editor'}
          canManageTemplate={myRole === 'owner'}
        />
      ),
    },
  ]

  const activeKey = section ?? activeTab
  const activeSection = tabs.find(t => t.key === activeKey)?.children

  return (
    <div className="workspace-settings-content">
      {section ? (
        <div data-testid={`ws-settings-section-${activeKey}`}>{activeSection}</div>
      ) : (
        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as WorkspaceSettingsSectionKey)}
          items={tabs}
          size={isMobile ? 'small' : 'middle'}
        />
      )}
    </div>
  )
}

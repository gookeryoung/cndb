/** 工作区设置 — 内容组件（可嵌入 Modal 或独立页面）.
 *
 * 包含三个分项：常规设置 / 权限管理 / 生命周期（统计信息为独立一级导航「统计」）
 * 常规设置只保留可编辑项，危险操作固定在内容底部（参考 GitHub 设置页）；
 * 角色信息与工作区只读信息并入「统计」页的概览分项。
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
  Tabs, Form, Input, Select, Switch, Tag, Button, Row, Col,
  Popconfirm, Card, Space, Avatar,
} from 'antd'
import { App as AntApp } from 'antd'
import {
  EyeOutlined, UserOutlined, DeleteOutlined, SafetyOutlined, SwapOutlined,
  SettingOutlined, ExclamationCircleOutlined,
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
import {
  DEFAULT_WORKSPACE_MODULES, normalizeModules,
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
          {/* 主列：可编辑的基本信息 */}
          <div className="cn-ws-settings-main">
              <Form
                form={form}
                layout="vertical"
                initialValues={{ visibility: 'member', tags: '', modules: [...DEFAULT_WORKSPACE_MODULES] }}
                onFinish={(v) => save.mutate(v)}
                disabled={!canEditBasic}
              >
                <Card
                  size="small"
                  title={<Space><SettingOutlined /> 基本信息</Space>}
                  className="cn-ws-basic-card"
                >
                  {/* 短字段三列并排（名称 / 公开性 / 标签），窄屏自动堆叠为单列 */}
                  <Row gutter={16}>
                    <Col xs={24} md={10}>
                      <Form.Item
                        name="name"
                        label="工作区名称"
                        rules={[{ required: true, message: '请输入名称' }]}
                      >
                        <Input placeholder="例如：产品研发" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="visibility"
                        label={<>公开性<HelpTip title="修改后立即生效：公开=任何人可读；成员可见=仅工作区成员可访问；私有=仅所有者可见" /></>}
                      >
                        <Select
                          options={Object.entries(VISIBILITY_LABEL).map(([v, l]) => ({ value: v, label: l }))}
                          disabled={!canEditBasic}
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={6}>
                      <Form.Item name="tags" label="标签（逗号分隔）">
                        <Input placeholder="例如：研发, 产品" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item name="description" label="描述（可选）">
                    <Input.TextArea rows={2} placeholder="简单介绍一下这个工作区" />
                  </Form.Item>
                  <Form.Item
                    name="modules"
                    className="cn-ws-basic-modules"
                    label={<>功能模块<HelpTip title="勾选工作区开放的功能：数据分析与数据同步随数据表一并启用，质量检查恒可用。修改后顶部页签与导航随之调整" /></>}
                  >
                    <ModuleCheckCards disabled={!canEditBasic} />
                  </Form.Item>
                  {!canEditBasic && (
                    <div className="cn-ws-basic-readonly-hint">
                      ℹ️ 您的角色（{ROLE_LABEL[myRole ?? 'viewer']}）仅能查看设置，无法修改
                    </div>
                  )}
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
                </Card>
              </Form>
          </div>

          {/* 危险操作区：参考 GitHub 设置页置于底部，仅 owner 可见。
           * 「转让所有权」与「删除工作区」都是不可逆操作，集中放在同一区域并用危险色提示。 */}
          {canDeleteWorkspace && (
            <div className="cn-ws-settings-danger" style={dangerBoxStyle}>
              <div className="cn-ws-settings-danger-title">
                <ExclamationCircleOutlined /> 危险操作
              </div>
              <div className="cn-ws-settings-danger-row">
                <div>
                  <div className="cn-ws-settings-danger-row-title">转让所有权</div>
                  <div className="cn-ws-settings-danger-row-desc">
                    将工作区转让给其他成员；转让后您将失去所有者特权，回落到编辑者角色。
                  </div>
                </div>
                <Button
                  danger
                  icon={<SwapOutlined />}
                  onClick={() => setTransferOpen(true)}
                >
                  转让所有权
                </Button>
              </div>
              <div className="cn-ws-settings-danger-row">
                <div>
                  <div className="cn-ws-settings-danger-row-title">删除此工作区</div>
                  <div className="cn-ws-settings-danger-row-desc">
                    删除后将永久删除所有数据表、数据行、视图和成员关系，无法恢复。
                  </div>
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
            </div>
          )}
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
      {/* 转让所有权弹窗：常规设置危险区与权限管理页共用同一实例，避免重复挂载 */}
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
}

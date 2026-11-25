/** 团队页（ADR 0153 / 需求 0157 C3）—— 多工作区统一管理的团队上下文.
 *
 * 口径（与后端一致）：
 * - 团队单层扁平、工作区在团队下是**平铺列表**（无树，ADR 0153 D2 / C1）；
 * - 团队角色只决定管理面：`team_owner` 改设置 / 策略 / 成员，`team_admin` 管成员，
 *   `team_member` 只读；团队管理员默认**读不到工作区数据**（D4）；
 * - 删除团队只解绑工作区（D9），文案必须说清「不删工作区数据」。
 *
 * 页面结构（需求 0157）：团队切换器 + 团队头部 + 分区页签（`?section=`），
 * 选中团队来自 URL（`/teams/:tid`），刷新 / 回退 / 分享保持。
 */

import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  App as AntApp, Button, Empty, Form, Input, Modal, Popover, Space, Tabs, Tag, Typography,
  type FormInstance,
} from 'antd'
import { ApartmentOutlined, PlusOutlined } from '@ant-design/icons'

import { teamApi, workspaceApi } from '@/api'
import type { Team, TeamMember, TeamPolicy, TeamWorkspace } from '@/api'
import { useResponsive } from '@/hooks/useResponsive'
import { TEAM_ROLE_COLOR, teamRoleLabel } from '@/utils/roleLabels'
import {
  TEAM_SECTIONS, normalizeTeamSection, teamSectionHref, type TeamSectionKey,
} from './teamSectionMeta'
import {
  TeamHeader, TeamMembersSection, TeamOverviewSection, TeamPolicySection, TeamSearchSection,
  TeamWorkspacesSection,
} from './TeamSections'

const { Text } = Typography

export default function TeamPage() {
  const queryClient = useQueryClient()
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const navigate = useNavigate()
  const { tid } = useParams<{ tid?: string }>()
  const [searchParams] = useSearchParams()
  const section = normalizeTeamSection(searchParams.get('section'))

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [policyForm] = Form.useForm()
  const [addMemberName, setAddMemberName] = useState('')
  const [addMemberRole, setAddMemberRole] = useState<'admin' | 'member'>('member')

  const { data: teams = [], isLoading } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
  })

  const active: Team | null = teams.find(t => String(t.id) === String(tid)) ?? null
  const activeId = active?.id
  const isOwner = active?.current_user_role === 'owner'
  const canManageMembers = isOwner || active?.current_user_role === 'admin'

  const { data: members = [], isLoading: membersLoading } = useQuery<TeamMember[]>({
    queryKey: ['team-members', activeId],
    queryFn: () => teamApi.members(activeId as number | string),
    enabled: !!activeId,
  })

  const { data: workspaces = [], isLoading: workspacesLoading } = useQuery<TeamWorkspace[]>({
    queryKey: ['team-workspaces', activeId],
    queryFn: () => teamApi.workspaces(activeId as number | string),
    enabled: !!activeId,
  })

  const joinWorkspace = useMutation({
    mutationFn: (wid: number | string) => workspaceApi.join(wid),
    onSuccess: () => {
      message.success('已加入工作区')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '加入工作区失败'),
  })

  function invalidateTeam() {
    queryClient.invalidateQueries({ queryKey: ['teams'] })
    queryClient.invalidateQueries({ queryKey: ['team-members', activeId] })
    queryClient.invalidateQueries({ queryKey: ['team-workspaces', activeId] })
    // 团队变更影响工作区能力位（管理面）与首页分组
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const create = useMutation({
    mutationFn: (values: { name: string; description?: string }) => teamApi.create(values),
    onSuccess: (team) => {
      message.success(`已创建团队「${team.name}」`)
      setCreateOpen(false)
      createForm.resetFields()
      invalidateTeam()
      navigate(`/teams/${team.id}`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建团队失败'),
  })

  const savePolicy = useMutation({
    mutationFn: (policy: TeamPolicy) => teamApi.update(activeId as number | string, { policy }),
    onSuccess: () => {
      message.success('团队策略已保存')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存策略失败'),
  })

  const removeTeam = useMutation({
    mutationFn: () => teamApi.remove(activeId as number | string),
    onSuccess: () => {
      message.success('团队已删除，其工作区已转为独立工作区（数据未删除）')
      invalidateTeam()
      navigate('/teams')
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除团队失败'),
  })

  const addMember = useMutation({
    mutationFn: () => teamApi.addMember(activeId as number | string, addMemberName.trim(), addMemberRole),
    onSuccess: () => {
      message.success('已添加团队成员')
      setAddMemberName('')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '添加成员失败'),
  })

  const changeRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: number | string; role: string }) =>
      teamApi.updateMember(activeId as number | string, memberId, role),
    onSuccess: () => {
      message.success('角色已更新')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新角色失败'),
  })

  const kick = useMutation({
    mutationFn: (memberId: number | string) => teamApi.removeMember(activeId as number | string, memberId),
    onSuccess: () => {
      message.success('已移除团队成员（其工作区成员身份不受影响）')
      invalidateTeam()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '移除成员失败'),
  })

  const goSection = (next: TeamSectionKey) => {
    if (!active) return
    navigate(teamSectionHref(active.id, next))
  }

  const createWorkspaceInTeam = () => {
    if (!active) return
    navigate(`/w?create=1&team=${active.id}`)
  }

  // ── 加载 / 空态 / 非法团队 ──
  if (isLoading) {
    return <div className="cn-state" data-testid="team-page-loading">加载中…</div>
  }

  if (teams.length === 0) {
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

  // `/teams` 与非法 id 统一回到第一个团队（深链 `/teams/:tid` 保持）
  if (!active) {
    if (!tid) return <Navigate to={`/teams/${teams[0].id}`} replace />
    return (
      <div style={{ padding: 24 }} data-testid="team-page-missing">
        <Empty description="团队不存在，或你无权访问">
          <Space>
            <Button type="primary" onClick={() => navigate(`/teams/${teams[0].id}`)}>返回我的团队</Button>
            <Button onClick={() => navigate('/w')}>回到工作区</Button>
          </Space>
        </Empty>
      </div>
    )
  }

  const sectionContent: Record<TeamSectionKey, ReactNode> = {
    overview: (
      <TeamOverviewSection
        team={active}
        isOwner={isOwner}
        canManageMembers={canManageMembers}
        onNavigateSection={goSection}
        members={members}
        membersLoading={membersLoading}
        workspaces={workspaces}
        workspacesLoading={workspacesLoading}
        onCreateWorkspace={createWorkspaceInTeam}
      />
    ),
    workspaces: (
      <TeamWorkspacesSection
        team={active}
        isOwner={isOwner}
        canManageMembers={canManageMembers}
        onNavigateSection={goSection}
        workspaces={workspaces}
        loading={workspacesLoading}
        onJoin={wid => joinWorkspace.mutate(wid)}
        joining={joinWorkspace.isPending}
        onCreateWorkspace={createWorkspaceInTeam}
      />
    ),
    members: (
      <TeamMembersSection
        team={active}
        isOwner={isOwner}
        canManageMembers={canManageMembers}
        onNavigateSection={goSection}
        members={members}
        loading={membersLoading}
        addName={addMemberName}
        setAddName={setAddMemberName}
        addRole={addMemberRole}
        setAddRole={setAddMemberRole}
        onAdd={() => addMember.mutate()}
        adding={addMember.isPending}
        onChangeRole={(memberId, role) => changeRole.mutate({ memberId, role })}
        onRemove={memberId => kick.mutate(memberId)}
      />
    ),
    policy: (
      <TeamPolicySection
        key={String(active.id)}
        team={active}
        isOwner={isOwner}
        canManageMembers={canManageMembers}
        onNavigateSection={goSection}
        form={policyForm}
        saving={savePolicy.isPending}
        onSave={policy => savePolicy.mutate(policy)}
        onDelete={() => removeTeam.mutate()}
        deleting={removeTeam.isPending}
      />
    ),
    search: (
      <TeamSearchSection
        team={active}
        isOwner={isOwner}
        canManageMembers={canManageMembers}
        onNavigateSection={goSection}
      />
    ),
  }

  return (
    <div style={{ padding: isMobile ? 12 : 24 }} data-testid="team-page">
      <div className="cn-team-toolbar">
        <TeamSwitcher teams={teams} activeId={active.id} onCreate={() => setCreateOpen(true)} />
        <Text type="secondary">团队只承载管理面与策略；数据权限仍在各工作区</Text>
      </div>

      <TeamHeader
        team={active}
        isOwner={isOwner}
        onCreateWorkspace={createWorkspaceInTeam}
        onManagePolicy={() => goSection('policy')}
      />

      <Tabs
        activeKey={section}
        onChange={(key) => goSection(normalizeTeamSection(key))}
        className="cn-team-tabs"
        items={TEAM_SECTIONS.map(item => ({
          key: item.key,
          label: (
            <span data-testid={`team-section-tab-${item.key}`}>
              {item.label}
              {item.key === 'workspaces' && <span className="cn-ws-tab-count">{active.workspace_count}</span>}
              {item.key === 'members' && <span className="cn-ws-tab-count">{active.member_count}</span>}
            </span>
          ),
        }))}
      />

      <div className="cn-team-section-body" data-testid={`team-section-${section}`}>
        {sectionContent[section]}
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

/** 团队切换器 —— 团队页头入口；列表带角色徽标，底部「新建团队」（C2 / C3） */
function TeamSwitcher({
  teams, activeId, onCreate,
}: {
  teams: Team[]
  activeId: number | string
  onCreate: () => void
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomLeft"
      arrow={false}
      content={(
        <div className="cn-scope-panel cn-team-switcher-panel" data-testid="team-switcher-panel">
          <div className="cn-scope-body">
            {teams.map(team => {
              const active = String(team.id) === String(activeId)
              return (
                <button
                  key={team.id}
                  type="button"
                  className={active ? 'cn-scope-row cn-scope-row-active' : 'cn-scope-row'}
                  data-testid={`team-switch-${team.id}`}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => { setOpen(false); navigate(`/teams/${team.id}`) }}
                >
                  <ApartmentOutlined className="cn-scope-row-icon" />
                  <span className="cn-scope-row-name">{team.name}</span>
                  <Tag color={TEAM_ROLE_COLOR[team.current_user_role ?? 'member']}>
                    {teamRoleLabel(team.current_user_role)}
                  </Tag>
                </button>
              )
            })}
          </div>
          <div className="cn-scope-footer">
            <Button
              type="text"
              size="small"
              icon={<PlusOutlined />}
              data-testid="team-switcher-create"
              onClick={() => { setOpen(false); onCreate() }}
            >
              新建团队
            </Button>
          </div>
        </div>
      )}
    >
      <Button icon={<ApartmentOutlined />} data-testid="team-switcher-btn" aria-label="切换团队">
        切换团队
      </Button>
    </Popover>
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
    <Modal
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      confirmLoading={loading}
      title="新建团队"
    >
      <Form form={form} layout="vertical" onFinish={onOk}>
        <Form.Item name="name" label="团队名称" rules={[{ required: true, message: '请输入团队名称' }]}>
          <Input placeholder="例如：研发部" maxLength={128} />
        </Form.Item>
        <Form.Item name="description" label="描述（可选）">
          <Input.TextArea rows={2} maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

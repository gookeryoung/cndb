/** 工作区列表页 — GitHub 风格可折叠行列表，支持创建/设置/导入/导出/收藏/搜索.
 *
 * 交互口径（参考 GitHub 仓库列表 / 文件树）：
 *  - 收起态只保留「收藏」与「展开」两个图标按钮，行内不堆操作，一屏能看更多工作区；
 *  - 展开后才出现描述、标签、数据表速览与「进入 / 设置 / 备份导出」等更多操作；
 *  - 收藏（置顶）复用后端 pin 状态，已收藏的工作区单独成组排在最前。
 */

import { useMemo, useState } from 'react'
import {
  Typography, Tag, Button, Modal, Form, Input, Select, Switch, Empty, App as AntApp,
  Upload, Alert, Progress, Skeleton, Tooltip, Radio, Space, Checkbox,
} from 'antd'
import {
  PlusOutlined, StarOutlined, StarFilled, CaretRightOutlined, TeamOutlined, TableOutlined,
  DownloadOutlined, SettingOutlined, GlobalOutlined, LockOutlined,
  SafetyCertificateOutlined, UploadOutlined, InboxOutlined, FileTextOutlined,
  FolderOpenOutlined, DatabaseOutlined, LoginOutlined, ArrowRightOutlined, HolderOutlined,
  ToolOutlined, WarningOutlined, ApartmentOutlined, UserOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useResponsive } from '@/hooks/useResponsive'
import SearchInput from '@/components/SearchInput'
import { useCreateParam } from '@/hooks/useCreateParam'
import { usePreferences, useSetWorkspaceOrder } from '@/hooks/useFavoriteViews'
import { useLandingOrder } from '@/hooks/useLandingOrder'
import { workspaceApi, tableApi, teamApi } from '@/api'
import type {
  Workspace, WorkspaceRole, WorkspaceVisibility, TableSummary, WorkspaceArchiveInspect, Team,
} from '@/api'
import {
  DEFAULT_WORKSPACE_MODULES, WORKSPACE_MODULE_LABEL, normalizeModules,
  workspaceLandingSegment, workspaceModulesFeatures,
} from '@/utils/workspaceModules'
import type { WorkspaceModule } from '@/utils/workspaceModules'
import ModuleCheckCards from '@/components/ModuleCheckCards'
import { sortWorkspaces } from '@/utils/homeOrder'
import { usePersistedState } from '@/utils/persistedState'
import {
  filterWorkspacesByScope, flattenGroupedOrder, groupWorkspacesByTeam, hasTeamGrouping,
  scopeOptions, type WorkspaceGroup, type WorkspaceScope,
} from './workspaceGroups'
import { formatDateTime, formatRelativeTime } from '@/utils/datetime'
import { teamRoleLabel } from '@/utils/roleLabels'
import WorkspaceSettingsModal from '@/pages/settings/WorkspaceSettingsModal'
import WorkspaceBackupDialog from '@/pages/settings/WorkspaceBackupDialog'
import MyViewsPanel from './MyViewsPanel'

const { Title, Text } = Typography

/** 工作区列表页携带统计信息的工作区视图模型 */
type WSWithStats = Workspace & {
  table_count?: number; member_count?: number;
  document_count?: number; design_count?: number;
  current_user_role?: WorkspaceRole | null;
}

/** 公开性图标 + 颜色映射 */
const VISIBILITY_META: Record<WorkspaceVisibility, { icon: React.ReactNode; color: string; label: string }> = {
  public: { icon: <GlobalOutlined />, color: 'green', label: '公开' },
  member: { icon: <SafetyCertificateOutlined />, color: 'blue', label: '成员可见' },
  private: { icon: <LockOutlined />, color: 'default', label: '私有' },
}

const ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者', editor: '编辑者', viewer: '查看者',
}

const ROLE_BADGE_COLOR: Record<WorkspaceRole, string> = {
  owner: 'gold', editor: 'cyan', viewer: 'default',
}

/** 功能模块徽标配色：标识勾选的功能范围（非权限），与公开性色系区分 */
const MODULE_TAG_COLOR: Record<WorkspaceModule, string> = {
  tables: 'geekblue', documents: 'orange', design: 'purple',
}

/** 行首图标：按首个勾选模块区分数据 / 文档 / 设计语义 */
const MODULE_ICON: Record<WorkspaceModule, React.ReactNode> = {
  tables: <DatabaseOutlined />,
  documents: <FileTextOutlined />,
  design: <ToolOutlined />,
}

/** 展开后速览的数据表数量上限（超出走「查看全部」，避免展开区无限长） */
const PREVIEW_TABLE_LIMIT = 8

export default function WorkspaceList() {
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  /** 新建弹窗预填的团队归属（团队页 / 团队 chip 进入时） */
  const [pendingTeamId, setPendingTeamId] = useState<number | undefined>()
  // 命令面板「新建工作区」经 URL ?create=1 触发（0067 C3）；团队页可带 ?team=<id> 预填归属
  useCreateParam((params) => {
    const teamId = Number(params.get('team'))
    setPendingTeamId(Number.isFinite(teamId) && teamId > 0 ? teamId : undefined)
    setCreateOpen(true)
  })
  const [settingsOpen, setSettingsOpen] = useState<Workspace | null>(null)
  const [backupOpen, setBackupOpen] = useState<Workspace | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [search, setSearch] = useState('')
  /** 首页团队筛选（需求 0157 C1）：全部 / 个人 / 团队 id；持久化，刷新后保持 */
  const [scope, setScope] = usePersistedState<WorkspaceScope>('cndb_home_scope', 'all')
  /** 折叠的团队分组 key（C8）：默认全部展开，只记用户手动收起过的组 */
  const [collapsedGroups, setCollapsedGroups] = usePersistedState<string[]>(
    'cndb_home_group_collapsed', [],
  )
  /** 已展开的工作区 id 集合（允许多行同时展开，与 GitHub 文件树一致） */
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [form] = Form.useForm()

  const { data: workspaces = [], isLoading } = useQuery<WSWithStats[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // 团队列表（ADR 0153）：用于工具栏过滤与「团队管理」入口；失败不阻断列表
  const { data: teams = [] } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
    retry: false,
  })

  // 主页自定义顺序（ADR 0021）：偏好缺失 / 读取失败时按 pinned → id 兜底
  const { data: prefs } = usePreferences()
  // 进入工作区的默认落地页顺序（需求 0161）：与偏好共用同一缓存
  const landingOrder = useLandingOrder()
  const setWorkspaceOrder = useSetWorkspaceOrder()
  const workspaceDragSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  )
  /** 持久化取值可能是字符串 / 已删除团队：归一为合法 scope，避免分类空白 */
  const effectiveScope: WorkspaceScope = useMemo(() => {
    if (scope === 'all' || scope === 'personal') return scope
    const id = Number(scope)
    if (teams.some(t => Number(t.id) === id)) return id
    return 'all'
  }, [scope, teams])

  const create = useMutation({
    mutationFn: (v: {
      name: string; description?: string;
      visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean;
      modules?: WorkspaceModule[]; team_id?: number | null;
    }) => workspaceApi.create({
      name: v.name,
      description: v.description ?? '',
      visibility: v.visibility ?? 'member',
      tags: v.tags ?? [],
      allow_edit: v.allow_edit ?? true,
      modules: normalizeModules(v.modules),
      team_id: v.team_id ?? null,
    }),
    onSuccess: (w) => {
      message.success(`已创建 "${w.name}"`)
      setCreateOpen(false)
      setPendingTeamId(undefined)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/w/${w.id}/${workspaceLandingSegment(w.modules, landingOrder)}`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建工作区失败，请重试'),
  })

  const pin = useMutation({
    mutationFn: (w: Workspace) => workspaceApi.togglePin(w.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
    onError: (err) => message.error(err instanceof Error ? err.message : '收藏失败'),
  })

  const toggleExpand = (id: number | string) => {
    const key = String(id)
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 排序（pinned 分组优先 → 自定义顺序 → id）→ 团队筛选 → 搜索过滤
  const filteredWorkspaces = useMemo(() => {
    const ordered = sortWorkspaces(workspaces, prefs?.workspace_order)
    const byTeam = filterWorkspacesByScope(ordered, effectiveScope)
    const q = search.trim().toLowerCase()
    if (!q) return byTeam
    return byTeam.filter(w =>
      (w.name ?? '').toLowerCase().includes(q) ||
      (w.description ?? '').toLowerCase().includes(q) ||
      (w.tags ?? []).some(t => t.toLowerCase().includes(q)),
    )
  }, [workspaces, search, prefs?.workspace_order, effectiveScope])

  /** 工作区 → 团队名（「我的视图」面板的收藏项要显示所属团队，避免只看到工作区名） */
  const teamByWorkspaceId = useMemo(() => new Map(
    workspaces
      .filter(ws => ws.team)
      .map(ws => [String(ws.id), ws.team!.name] as const),
  ), [workspaces])

  const starred = filteredWorkspaces.filter(w => w.pinned)
  /** 是否展示团队层级（无团队归属时保持现状，C9） */
  const showTeamGrouping = hasTeamGrouping(teams, workspaces)
  /** 展示分组：有团队层级时按团队分组；否则保持原「其他工作区」单组 */
  const groups = useMemo<Array<WorkspaceGroup<WSWithStats>>>(() => {
    if (showTeamGrouping) return groupWorkspacesByTeam(filteredWorkspaces, teams)
    const others = filteredWorkspaces.filter(w => !w.pinned)
    if (others.length === 0) return []
    return [{ key: 'others', teamId: null, title: '其他工作区', isPersonal: true, workspaces: others }]
  }, [showTeamGrouping, filteredWorkspaces, teams])
  /** 团队 chips（全部 / 个人 / 各团队）：默认全部，点击收窄，再次点击回到全部 */
  const teamChips = useMemo(() => scopeOptions(teams, workspaces), [teams, workspaces])
  /** 搜索 / 团队筛选时禁止拖拽：保存的是全量顺序，只提交可见子集会误伤未展示工作区的名次 */
  const dragEnabled = !search.trim() && effectiveScope === 'all'

  const toggleGroupCollapsed = (key: string) => {
    setCollapsedGroups(prev => (
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    ))
  }

  /** 组内拖拽结束：跨分组不生效；保存时按当前分组顺序拼接全量 id */
  const handleWorkspaceDragEnd = (event: DragEndEvent) => {
    if (!dragEnabled) return
    const { active, over } = event
    if (!over || active.id === over.id) return
    const byId = new Map(workspaces.map(w => [String(w.id), w]))
    const activeWs = byId.get(String(active.id))
    const overWs = byId.get(String(over.id))
    if (!activeWs || !overWs) return

    const activeGroup = activeWs.pinned
      ? null
      : groups.find(g => g.workspaces.some(w => String(w.id) === String(active.id)))
    const overGroup = overWs.pinned
      ? null
      : groups.find(g => g.workspaces.some(w => String(w.id) === String(over.id)))
    if (!!activeWs.pinned !== !!overWs.pinned) return
    if (!activeWs.pinned && (!activeGroup || activeGroup.key !== overGroup?.key)) return

    const groupRows = activeWs.pinned ? starred : (activeGroup?.workspaces ?? [])
    const groupIds = groupRows.map(w => String(w.id))
    const from = groupIds.indexOf(String(active.id))
    const to = groupIds.indexOf(String(over.id))
    if (from < 0 || to < 0) return
    const nextGroup = arrayMove(groupIds, from, to)
    const reorder = () => nextGroup
      .map(id => byId.get(id))
      .filter((w): w is WSWithStats => !!w)
    // 已收藏组内拖拽：重排 starred；未收藏组内拖拽：只重排目标组，starred 原样保留
    const orderedStarred = activeWs.pinned ? reorder() : starred
    const nextGroups = activeWs.pinned
      ? groups
      : groups.map(g => (g.key === activeGroup?.key ? { ...g, workspaces: reorder() } : g))
    setWorkspaceOrder.mutate(flattenGroupedOrder(orderedStarred, nextGroups), {
      onError: (err) => message.error(err instanceof Error ? err.message : '保存排序失败，请重试'),
    })
  }

  /** 行渲染：拖拽把手 + 收起态图标 + 展开详情（拖拽只在把手生效）。
   *
   * `showTeam`：仅「已收藏」组传 true —— 该组是跨团队的扁平列表（收藏置顶后脱离了团队分组），
   * 行内补团队归属才不会让人看不出收藏的工作区属于哪个团队。 */
  const renderRow = (w: WSWithStats, showTeam = false) => (
    <WorkspaceRow
      key={w.id}
      ws={w}
      showTeam={showTeam}
      expanded={expandedIds.has(String(w.id))}
      draggable={dragEnabled}
      isMobile={isMobile}
      onToggle={() => toggleExpand(w.id)}
      onPin={() => pin.mutate(w)}
      onSettings={() => setSettingsOpen(w)}
      onBackup={() => setBackupOpen(w)}
      landingOrder={landingOrder}
    />
  )

  return (
    <div className="cn-page cn-home-page" data-testid="workspace-list">
      {/* 左右双板块：左侧「我的工作区」卡片（标题 + 搜索 + 新建/导入 + 列表）与右侧「我的视图」卡片同高。
          内容宽度由 `.cn-home-page` 的 max-width 收口（需求 0160 C2）：超宽屏不再把行拉成两头空。 */}
      <div className="cn-home-split" data-testid="workspace-home-split">
        <div className="cn-home-main">
          {/* 工具栏 —— 移动端纵向堆叠：标题整行、搜索框占满、按钮均分，避免固定宽度导致横向溢出 */}
          <div
            data-testid="workspace-list-toolbar"
            style={{
              display: 'flex',
              flexDirection: isMobile ? 'column' : 'row',
              justifyContent: 'space-between',
              alignItems: isMobile ? 'stretch' : 'center',
              marginBottom: 16,
              flexWrap: 'wrap',
              gap: 12,
            }}
          >
            <div>
              <Title level={3} style={{ margin: 0 }}><FolderOpenOutlined style={{ marginRight: 8 }} />我的工作区</Title>
              <Text type="secondary">
                {showTeamGrouping ? '按团队分组浏览；收藏工作区置顶，团队内工作区平铺' : '选择或创建一个工作区开始协作'}
              </Text>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <SearchInput
                size="middle"
                placeholder="搜索工作区名称/标签…"
                style={{ width: isMobile ? '100%' : 260 }}
                value={search}
                onChange={e => setSearch((e.target as HTMLInputElement).value)}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  setPendingTeamId(typeof effectiveScope === 'number' ? effectiveScope : undefined)
                  setCreateOpen(true)
                }}
                style={isMobile ? { flex: 1 } : undefined}
                data-testid="create-workspace-btn"
              >
                新建工作区
              </Button>
              <Button
                icon={<UploadOutlined />}
                onClick={() => setImportOpen(true)}
                style={isMobile ? { flex: 1 } : undefined}
                data-testid="import-workspace-btn"
              >
                导入工作区
              </Button>
            </div>
          </div>

          {teams.length > 0 && (
            <div className="cn-ws-team-chips" data-testid="workspace-team-chips" role="group" aria-label="按团队筛选工作区">
              {teamChips.map(chip => {
                const active = String(effectiveScope) === String(chip.value)
                return (
                  <button
                    key={String(chip.value)}
                    type="button"
                    className={active ? 'cn-ws-team-chip cn-ws-team-chip-active' : 'cn-ws-team-chip'}
                    aria-pressed={active}
                    data-testid={`workspace-team-chip-${chip.value}`}
                    onClick={() => setScope(active ? 'all' : chip.value)}
                  >
                    {chip.label}
                    <span className="cn-ws-team-chip-count">{chip.count}</span>
                  </button>
                )
              })}
            </div>
          )}

          {isLoading ? (
            /* 骨架屏占位 —— 行式布局，sr-only 文本保留给屏幕阅读器与既有测试断言 */
            <div data-testid="workspace-list-skeleton" role="status">
              <span style={{
                position: 'absolute', width: 1, height: 1, overflow: 'hidden',
                clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap',
              }}>加载中...</span>
              <div className="cn-ws-list">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div className="cn-ws-row" key={i}>
                    <div className="cn-ws-row-main">
                      <Skeleton active title={false} paragraph={{ rows: 1, width: '60%' }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : filteredWorkspaces.length === 0 ? (
            <Empty description={search ? `没有匹配「${search}」的工作区` : '还没有工作区，创建一个吧！'}>
              {/* 空态即引导（需求 0160 C5）：首屏直接给出三个真实入口，而不是只有一行说明文字 */}
              {!search && (
                <Space wrap style={{ marginTop: 16, justifyContent: 'center' }}>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    data-testid="empty-create-workspace"
                    onClick={() => {
                      setPendingTeamId(typeof effectiveScope === 'number' ? effectiveScope : undefined)
                      setCreateOpen(true)
                    }}
                  >
                    新建工作区
                  </Button>
                  <Button
                    icon={<UploadOutlined />}
                    data-testid="empty-import-workspace"
                    onClick={() => setImportOpen(true)}
                  >
                    导入备份
                  </Button>
                  {teams.length > 0 && (
                    <Button icon={<TeamOutlined />} onClick={() => navigate('/teams')}>
                      我的团队
                    </Button>
                  )}
                </Space>
              )}
            </Empty>
          ) : (
            <DndContext
              sensors={workspaceDragSensors}
              collisionDetection={closestCenter}
              onDragEnd={handleWorkspaceDragEnd}
            >
              <div className="cn-ws-groups">
                {starred.length > 0 && (
                  <section className="cn-ws-group" data-testid="workspace-group-starred">
                    <div className="cn-ws-group-head">
                      <StarFilled style={{ color: '#f59e0b' }} />
                      <span>收藏工作区</span>
                      <span className="cn-ws-group-count">{starred.length}</span>
                    </div>
                    <SortableContext
                      items={starred.map(w => String(w.id))}
                      strategy={verticalListSortingStrategy}
                    >
                      <div className="cn-ws-list">{starred.map(w => renderRow(w, true))}</div>
                    </SortableContext>
                  </section>
                )}
                {groups.map((group) => {
                  const collapsed = collapsedGroups.includes(group.key)
                  // 无团队层级时沿用旧 testid 与「无收藏不显示组头」口径，存量行为不变（C9）
                  const testid = group.key === 'others'
                    ? 'workspace-group-others'
                    : `workspace-group-${group.key}`
                  const showHead = group.key !== 'others' || starred.length > 0
                  return (
                    <section
                      key={group.key}
                      className="cn-ws-group"
                      data-testid={testid}
                      data-collapsed={collapsed ? 'true' : undefined}
                    >
                      {showHead && (
                        <div className="cn-ws-group-head">
                          <button
                            type="button"
                            className="cn-ws-group-toggle"
                            aria-expanded={!collapsed}
                            aria-label={`${collapsed ? '展开' : '收起'}「${group.title}」`}
                            data-testid={`workspace-group-toggle-${group.key}`}
                            onClick={() => toggleGroupCollapsed(group.key)}
                          >
                            <CaretRightOutlined rotate={collapsed ? 0 : 90} />
                          </button>
                          {group.isPersonal ? <UserOutlined /> : <TeamOutlined />}
                          <span className="cn-ws-group-title">{group.title}</span>
                          <span className="cn-ws-group-count">{group.workspaces.length}</span>
                          {!group.isPersonal && group.team && (
                            <Button
                              type="link"
                              size="small"
                              className="cn-ws-group-manage"
                              data-testid={`workspace-group-manage-${group.team.id}`}
                              onClick={() => navigate(`/teams/${group.team!.id}`)}
                            >
                              管理
                            </Button>
                          )}
                        </div>
                      )}
                      {!collapsed && (
                        <SortableContext
                          items={group.workspaces.map(w => String(w.id))}
                          strategy={verticalListSortingStrategy}
                        >
                          <div className="cn-ws-list">{group.workspaces.map(w => renderRow(w))}</div>
                        </SortableContext>
                      )}
                    </section>
                  )
                })}
              </div>
            </DndContext>
          )}
        </div>

        {/* 右侧「我的视图」：桌面固定宽分栏，<992px 由 CSS 堆叠到工作区下方 */}
        <aside className="cn-home-aside" data-testid="workspace-home-aside">
          <MyViewsPanel teamByWorkspaceId={teamByWorkspaceId} />
        </aside>
      </div>

      {/* 我的团队板块（2026-11-26 新增）：主页内容区常驻团队入口，行内标注角色与规模 */}
      {teams.length > 0 && (
        <section className="cn-home-teams" data-testid="home-teams-panel" aria-label="我的团队">
          <header className="cn-myviews-head">
            <TeamOutlined />
            <span className="cn-myviews-title">我的团队</span>
            <span className="cn-myviews-count" data-testid="home-teams-count">{teams.length}</span>
          </header>
          <div className="cn-home-teams-list">
            {teams.map(team => (
              <button
                key={team.id}
                type="button"
                className="cn-home-teams-row"
                data-testid={`home-team-row-${team.id}`}
                onClick={() => navigate(`/teams/${team.id}`)}
              >
                <span className="cn-home-teams-icon" aria-hidden><ApartmentOutlined /></span>
                <span className="cn-home-teams-name">{team.name}</span>
                <span className="cn-home-teams-hint">
                  {teamRoleLabel(team.current_user_role)} · {team.member_count ?? 0} 成员 · {team.workspace_count ?? 0} 工作区
                </span>
                <ArrowRightOutlined className="cn-home-teams-arrow" aria-hidden />
              </button>
            ))}
          </div>
        </section>
      )}

      {/* 新建工作区 Modal — 扩展字段；条件渲染避免 Form.useForm 在未挂载时触发 warning */}
      {createOpen && (
        <Modal
          title="新建工作区"
          open={createOpen}
          onCancel={() => { form.resetFields(); setPendingTeamId(undefined); setCreateOpen(false) }}
          onOk={() => form.submit()}
          confirmLoading={create.isPending}
          okText="创建"
          data-testid="create-workspace-modal"
          width={520}
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              visibility: 'member', allow_edit: true,
              modules: [...DEFAULT_WORKSPACE_MODULES],
              team_id: pendingTeamId,
            }}
            onFinish={(v) => {
              const tagsStr = (v.tags as string) || ''
              create.mutate({
                ...v,
                tags: tagsStr.split(/[,，]/).map(s => s.trim()).filter(Boolean),
              })
            }}
          >
            <Form.Item name="name" label="工作区名称" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="例如：产品研发" />
            </Form.Item>
            <Form.Item name="description" label="描述（可选）">
              <Input.TextArea rows={2} placeholder="简单介绍一下这个工作区" />
            </Form.Item>
            <Form.Item
              name="modules"
              label="功能模块"
              extra="按需勾选工作区开放的功能；数据分析与数据同步随数据表一并启用，质量检查恒可用。"
            >
              <ModuleCheckCards />
            </Form.Item>
            <Form.Item name="visibility" label="公开性">
              <Select
                options={[
                  { value: 'public', label: '公开（同团队成员可读）' },
                  { value: 'member', label: '成员可见（推荐）' },
                  { value: 'private', label: '私有（仅所有者可见）' },
                ]}
              />
            </Form.Item>
            {teams.length > 0 && (
              <Form.Item
                name="team_id"
                label="所属团队（可选）"
                extra="挂到团队后，团队所有者/管理员可管理工作区设置；数据权限仍由工作区成员决定"
              >
                <Select
                  allowClear
                  placeholder="个人工作区（不归属团队）"
                  data-testid="create-workspace-team"
                  options={teams.map(t => ({ value: t.id, label: t.name }))}
                />
              </Form.Item>
            )}
            <Form.Item name="tags" label="标签（逗号分隔，可选）">
              <Input placeholder="例如：研发, 产品, 核心业务" />
            </Form.Item>
            <Form.Item name="allow_edit" label="允许成员编辑数据" valuePropName="checked">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Switch />
                <span style={{ color: '#64748b', fontSize: 'var(--cn-text-sm)' }}>
                  {form.getFieldValue('allow_edit') !== false ? '已开启' : '已关闭（仅所有者可编辑）'}
                </span>
              </div>
            </Form.Item>
          </Form>
        </Modal>
      )}

      {/* 设置 Modal */}
      {settingsOpen && (
        <WorkspaceSettingsModal
          open={!!settingsOpen}
          wid={String(settingsOpen.id)}
          onClose={() => setSettingsOpen(null)}
          onUpdated={() => queryClient.invalidateQueries({ queryKey: ['workspaces'] })}
        />
      )}

      {/* 备份 Modal */}
      {backupOpen && (
        <WorkspaceBackupDialog
          open={!!backupOpen}
          wid={String(backupOpen.id)}
          workspaceName={backupOpen.name}
          onClose={() => setBackupOpen(null)}
        />
      )}

      {/* 导入工作区 Modal — 全量归档导入：默认新建工作区；同名 owner 工作区可覆盖恢复 */}
      {importOpen && <ImportWorkspaceModal
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onImported={(w) => {
          setImportOpen(false)
          queryClient.invalidateQueries({ queryKey: ['workspaces'] })
          message.success(`已导入工作区「${w.name}」`)
          navigate(`/w/${w.id}/${workspaceLandingSegment(w.modules, landingOrder)}`)
        }}
        onRestored={() => {
          setImportOpen(false)
          queryClient.invalidateQueries({ queryKey: ['workspaces'] })
          message.success('已覆盖恢复到所选工作区')
        }}
        onError={(err) => message.error(err instanceof Error ? err.message : '导入失败')}
      />}
    </div>
  )
}

/** 单个工作区行 —— 拖拽把手独立于行点击区域.
 *
 * 拖拽监听只挂在把手上（PointerSensor 距离阈值 4px），避免拖拽释放后误触进入工作区；
 * 搜索过滤时 `draggable=false`，把手降级为普通图标，防止只提交过滤后的子集顺序。
 */
function WorkspaceRow({
  ws, expanded, draggable, isMobile, landingOrder, showTeam = false,
  onToggle, onPin, onSettings, onBackup,
}: {
  ws: WSWithStats
  expanded: boolean
  draggable: boolean
  isMobile: boolean
  /** 是否在行内展示所属团队（「已收藏」组用：该组跨团队扁平，缺归属就分不清） */
  showTeam?: boolean
  /** 进入本工作区的默认落地页优先级（需求 0161） */
  landingOrder: WorkspaceModule[]
  onToggle: () => void
  onPin: () => void
  onSettings: () => void
  onBackup: () => void
}) {
  const navigate = useNavigate()
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: String(ws.id),
    disabled: !draggable,
  })
  const vis = VISIBILITY_META[(ws.visibility ?? 'member') as WorkspaceVisibility]
    ?? VISIBILITY_META.member
  const role = ws.current_user_role ?? null
  const modules = normalizeModules(ws.modules)
  const landing = `/w/${ws.id}/${workspaceLandingSegment(modules, landingOrder)}`

  return (
    <div
      ref={setNodeRef}
      className={`cn-ws-row${expanded ? ' is-expanded' : ''}`}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
        zIndex: isDragging ? 2 : undefined,
      }}
      data-testid={`workspace-row-${ws.id}`}
    >
      <div className="cn-ws-row-main" onClick={() => navigate(landing)}>
        <Tooltip title={draggable ? '拖拽调整顺序' : '搜索过滤时不可拖拽'}>
          <Button
            type="text"
            size="small"
            className="cn-ws-row-drag"
            aria-label={`拖拽排序「${ws.name}」`}
            data-testid={`workspace-drag-${ws.id}`}
            icon={<HolderOutlined />}
            disabled={!draggable}
            onClick={(e) => e.stopPropagation()}
            {...attributes}
            {...(draggable ? listeners : undefined)}
          />
        </Tooltip>

        <Tooltip title={expanded ? '收起详情' : '展开详情'}>
          <Button
            type="text"
            size="small"
            className="cn-ws-row-toggle"
            aria-expanded={expanded}
            aria-label={`${expanded ? '收起' : '展开'}「${ws.name}」`}
            data-testid={`workspace-expand-${ws.id}`}
            icon={<CaretRightOutlined rotate={expanded ? 90 : 0} />}
            onClick={(e) => { e.stopPropagation(); onToggle() }}
          />
        </Tooltip>

        <span className="cn-ws-row-icon" aria-hidden>{MODULE_ICON[modules[0]]}</span>

        {/* 标题与次要信息同属可换行 body：宽度不足时 meta 落到第二行，而不是把名称压没（需求 0157 列表优化） */}
        <div className="cn-ws-row-body">
          <div className="cn-ws-row-title">
            <span className="cn-ws-row-name" title={ws.name}>{ws.name}</span>
            {showTeam && ws.team && (
              <Tag
                icon={<ApartmentOutlined />}
                className="cn-ws-row-tag cn-ws-row-tag--team"
                /* 与模块徽标同口径：窄桌面收起文字徽标，团队名仍在展开详情与 hover 提示里 */
                data-testid={`workspace-team-tag-${ws.id}`}
              >
                {ws.team.name}
              </Tag>
            )}
            <Tooltip title={vis.label}>
              <span className="cn-ws-row-vis" style={{ color: 'var(--cn-text-muted)' }} aria-label={vis.label}>
                {vis.icon}
              </span>
            </Tooltip>
            {/* 模块徽标只在桌面渲染（<1280 由 CSS 隐藏）：文字徽标不可收缩，会挤占名称（模块信息由行首图标与展开详情承载） */}
            {!isMobile && modules.map(m => (
              <Tag key={m} color={MODULE_TAG_COLOR[m]} className="cn-ws-row-tag cn-ws-row-tag--module">
                {WORKSPACE_MODULE_LABEL[m]}
              </Tag>
            ))}
            {role && (
              <Tag color={ROLE_BADGE_COLOR[role]} className="cn-ws-row-tag">
                {ROLE_LABEL[role]}
              </Tag>
            )}
          </div>

          {!isMobile && (
            <div className="cn-ws-row-meta">
              <span><TableOutlined /> {ws.table_count ?? 0}</span>
              <span><TeamOutlined /> {ws.member_count ?? 1}</span>
              {ws.allow_edit === false && (
                <Tooltip title="编辑已关闭：仅所有者可编辑数据">
                  <span className="cn-ws-row-locked"><LockOutlined /> 只读</span>
                </Tooltip>
              )}
              {ws.updated_at && (
                <span className="cn-ws-row-time" title={formatDateTime(ws.updated_at)}>
                  {/* 宽屏给精确时间；1024–1279 换成相对时间；<1024 由 CSS 整体隐藏 */}
                  <span className="cn-ws-row-time-abs">{formatDateTime(ws.updated_at)}</span>
                  <span className="cn-ws-row-time-rel">{formatRelativeTime(ws.updated_at)}</span>
                </span>
              )}
            </div>
          )}
        </div>

        <div className="cn-ws-row-actions">
          <Tooltip title={ws.pinned ? '取消收藏' : '收藏'}>
            <Button
              type="text"
              size="small"
              aria-pressed={!!ws.pinned}
              aria-label={ws.pinned ? `取消收藏「${ws.name}」` : `收藏「${ws.name}」`}
              data-testid={`star-btn-${ws.id}`}
              icon={ws.pinned ? <StarFilled style={{ color: '#f59e0b' }} /> : <StarOutlined />}
              onClick={(e) => { e.stopPropagation(); onPin() }}
            />
          </Tooltip>
        </div>
      </div>

      {expanded && (
        <WorkspaceRowDetail
          ws={ws}
          onOpen={() => navigate(landing)}
          onSettings={onSettings}
          onBackup={onBackup}
        />
      )}
    </div>
  )
}

/** 展开区 —— 描述 / 标签 / 数据表速览 / 更多操作.
 *
 * 数据表列表按需拉取（收起态不发请求），queryKey 与 TablesList 对齐可直接命中缓存。
 */
function WorkspaceRowDetail({
  ws, onOpen, onSettings, onBackup,
}: {
  ws: WSWithStats
  onOpen: () => void
  onSettings: () => void
  onBackup: () => void
}) {
  const navigate = useNavigate()
  const features = workspaceModulesFeatures(ws.modules)

  const { data: tables = [], isLoading } = useQuery<TableSummary[]>({
    queryKey: ['workspaces', ws.id, 'tables'],
    queryFn: () => tableApi.list(ws.id),
    enabled: features.tables,
    staleTime: 30_000,
  })

  const preview = tables.slice(0, PREVIEW_TABLE_LIMIT)
  const tags = ws.tags ?? []

  return (
    <div
      className="cn-ws-detail"
      data-testid={`workspace-detail-${ws.id}`}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="cn-ws-detail-desc">{ws.description || '暂无描述'}</div>

      {(tags.length > 0 || ws.team) && (
        <div className="cn-ws-detail-tags">
          {ws.team && (
            <Tag icon={<ApartmentOutlined />} color="geekblue" style={{ marginInlineEnd: 0 }}>
              {ws.team.name}
            </Tag>
          )}
          {tags.map(t => <Tag key={t} style={{ marginInlineEnd: 0 }}>{t}</Tag>)}
        </div>
      )}

      {ws.allow_edit === false && (
        <div className="cn-ws-detail-note">
          <LockOutlined /> 编辑已关闭：成员只能查看数据，仅所有者可编辑
        </div>
      )}

      {features.tables && (
        <div className="cn-ws-detail-section">
          <div className="cn-ws-detail-section-head">
            <span>数据表</span>
            <span className="cn-ws-detail-section-count">
              {isLoading ? '加载中…' : `共 ${tables.length} 张`}
            </span>
          </div>
          {!isLoading && tables.length > 0 && (
            <div className="cn-ws-detail-tables">
              {preview.map(t => (
                <button
                  key={t.id}
                  type="button"
                  className="cn-ws-detail-table"
                  data-testid={`workspace-detail-table-${t.id}`}
                  onClick={() => navigate(`/w/${ws.id}/tables/${t.id}`)}
                >
                  <TableOutlined />
                  <span className="cn-ws-detail-table-name">{t.name}</span>
                  <span className="cn-ws-detail-table-count">{t.record_count ?? 0}</span>
                </button>
              ))}
              {tables.length > preview.length && (
                <button
                  type="button"
                  className="cn-ws-detail-table cn-ws-detail-table--more"
                  onClick={onOpen}
                >
                  查看全部 {tables.length} 张 <ArrowRightOutlined />
                </button>
              )}
            </div>
          )}
          {!isLoading && tables.length === 0 && (
            <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>还没有数据表</Text>
          )}
        </div>
      )}

      {features.documents && (
        <div className="cn-ws-detail-section" data-testid={`workspace-detail-documents-${ws.id}`}>
          <div className="cn-ws-detail-section-head">
            <span>文档</span>
            <span className="cn-ws-detail-section-count">共 {ws.document_count ?? 0} 篇</span>
          </div>
          {(ws.document_count ?? 0) > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>进入文档区查看目录与最近更新</Text>
              <Button
                type="link"
                size="small"
                style={{ padding: 0, height: 'auto' }}
                data-testid={`workspace-detail-documents-open-${ws.id}`}
                onClick={() => navigate(`/w/${ws.id}/documents`)}
              >
                查看 <ArrowRightOutlined />
              </Button>
            </div>
          ) : (
            <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>还没有文档</Text>
          )}
        </div>
      )}

      {features.design && (
        <div className="cn-ws-detail-section" data-testid={`workspace-detail-design-${ws.id}`}>
          <div className="cn-ws-detail-section-head">
            <span>设计</span>
            <span className="cn-ws-detail-section-count">共 {ws.design_count ?? 0} 个</span>
          </div>
          {(ws.design_count ?? 0) > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>进入设计区查看零件 / 装配文件</Text>
              <Button
                type="link"
                size="small"
                style={{ padding: 0, height: 'auto' }}
                data-testid={`workspace-detail-design-open-${ws.id}`}
                onClick={() => navigate(`/w/${ws.id}/design`)}
              >
                查看 <ArrowRightOutlined />
              </Button>
            </div>
          ) : (
            <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>还没有设计</Text>
          )}
        </div>
      )}

      <div className="cn-ws-detail-actions">
        <Button type="primary" size="small" icon={<LoginOutlined />} onClick={onOpen} data-testid={`enter-btn-${ws.id}`}>
          进入工作区
        </Button>
        <Button size="small" icon={<SettingOutlined />} onClick={onSettings} data-testid={`settings-btn-${ws.id}`}>
          工作区设置
        </Button>
        <Button size="small" icon={<DownloadOutlined />} onClick={onBackup} data-testid={`backup-btn-${ws.id}`}>
          备份导出
        </Button>
      </div>
    </div>
  )
}

/** 允许导入的归档扩展名（仅全量归档，JSON 备份格式已下线） */
const ACCEPTED_ARCHIVE_EXT = ['.tar.gz', '.tgz']

/** 导入为新工作区的默认名称：归档内名称 + 导入时间后缀（用户可修改） */
function defaultImportWorkspaceName(base: string): string {
  return `${base}（导入 ${formatDateTime(new Date().toISOString())}）`
}

interface ImportWorkspaceModalProps {
  open: boolean
  onCancel: () => void
  /** 导入为新工作区成功（避免覆盖任何现有数据，默认选项） */
  onImported: (w: Workspace) => void
  /** 覆盖恢复到同名既有工作区成功（仅 owner 可见该选项） */
  onRestored: (wid: number | string) => void
  onError: (err: unknown) => void
}

function ImportWorkspaceModal({ open, onCancel, onImported, onRestored, onError }: ImportWorkspaceModalProps) {
  const [importing, setImporting] = useState(false)
  const [inspecting, setInspecting] = useState(false)
  const [importResult, setImportResult] = useState<{ tables: number; rows: number; views: number; documents: number } | null>(null)
  const [pendingArchive, setPendingArchive] = useState<File | null>(null)
  const [inspect, setInspect] = useState<WorkspaceArchiveInspect | null>(null)
  // 导入为新工作区时的名称：默认加导入时间后缀便于区分，允许用户修改
  const [newName, setNewName] = useState('')
  // 默认导入为新工作区（推荐）；仅当归档目标同名工作区已存在且当前用户为 owner 才允许覆盖恢复
  const [mode, setMode] = useState<'new' | 'restore'>('new')
  const [confirmChecked, setConfirmChecked] = useState(false)
  const [confirmName, setConfirmName] = useState('')

  const existing = inspect?.existing_workspace ?? null
  const restoreReady = !!existing && confirmChecked && confirmName === inspect?.workspace_name
  const newNameReady = mode === 'restore' || !!newName.trim()

  const reset = () => {
    setImportResult(null)
    setPendingArchive(null)
    setInspect(null)
    setNewName('')
    setMode('new')
    setConfirmChecked(false)
    setConfirmName('')
    setInspecting(false)
  }

  const beforeUpload = async (file: File) => {
    const name = file.name.toLowerCase()
    if (!ACCEPTED_ARCHIVE_EXT.some(ext => name.endsWith(ext))) {
      onError(new Error('仅支持全量归档文件（.tar.gz）'))
      return false
    }
    setPendingArchive(file)
    setImportResult(null)
    setInspect(null)
    setNewName('')
    setMode('new')
    setConfirmChecked(false)
    setConfirmName('')
    setInspecting(true)
    try {
      const info = await workspaceApi.inspectWorkspaceArchive(file)
      setInspect(info)
      setNewName(defaultImportWorkspaceName(info.workspace_name))
    } catch (err) {
      setPendingArchive(null)
      onError(err)
    } finally {
      setInspecting(false)
    }
    // 返回 false 阻止 Upload 组件自动上传，手动在 onOk 里提交
    return false
  }

  const handleSubmit = async () => {
    if (!pendingArchive) {
      onError(new Error('请先选择全量归档文件'))
      return
    }
    if (mode === 'restore' && (!existing || !restoreReady)) return
    if (mode === 'new' && !newName.trim()) {
      onError(new Error('请输入新工作区名称'))
      return
    }

    try {
      setImporting(true)
      if (mode === 'restore' && existing) {
        const result = await workspaceApi.restoreWorkspace(existing.id, pendingArchive)
        setImportResult({
          tables: result.imported_tables,
          rows: result.imported_rows,
          views: result.imported_views,
          documents: result.imported_documents ?? 0,
        })
        const restoredId = existing.id
        setTimeout(() => { reset(); onRestored(restoredId) }, 800)
        return
      }
      const result = await workspaceApi.importWorkspaceArchive(pendingArchive, newName)
      setImportResult({
        tables: result.imported_tables,
        rows: result.imported_rows,
        views: result.imported_views,
        documents: result.imported_documents ?? 0,
      })
      const imported = result.workspace
      setTimeout(() => { reset(); onImported(imported) }, 800)
    } catch (err) {
      onError(err)
    } finally {
      setImporting(false)
    }
  }

  return (
    <Modal
      title="导入工作区"
      open={open}
      onCancel={() => { reset(); onCancel() }}
      onOk={handleSubmit}
      confirmLoading={importing}
      okText={mode === 'restore' ? '覆盖恢复' : '导入为新工作区'}
      okButtonProps={{
        danger: mode === 'restore',
        disabled: !pendingArchive || inspecting || !newNameReady
          || (mode === 'restore' && !restoreReady),
      }}
      cancelText="取消"
      destroyOnHidden
      width={600}
    >
      <Text type="secondary" style={{ display: 'block', fontSize: 'var(--cn-text-xs)', marginBottom: 12 }}>
        默认导入为新工作区，不覆盖现有数据
      </Text>

      {!importResult && (
        <div style={{ marginBottom: 16 }}>
          <Upload.Dragger
            multiple={false}
            accept={ACCEPTED_ARCHIVE_EXT.join(',')}
            beforeUpload={beforeUpload}
            disabled={importing || inspecting}
            showUploadList={false}
          >
            <p className="ant-upload-text" style={{ margin: 0, fontSize: 'var(--cn-text-sm)' }}>
              <InboxOutlined style={{ marginInlineEnd: 6 }} />
              点击或拖拽 .tar.gz 全量归档到此处
            </p>
          </Upload.Dragger>
        </div>
      )}

      {inspecting && (
        <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--cn-text-secondary)' }}>
          正在读取归档信息…
        </div>
      )}

      {inspect && !importResult && (
        <div data-testid="import-archive-inspect" style={{ marginBottom: 16 }}>
          <Space size={8} wrap>
            <Text strong>{inspect.workspace_name}</Text>
            <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
              {[
                `v${inspect.backup_version}`,
                inspect.stats?.tables !== undefined ? `${inspect.stats.tables} 表` : '',
                inspect.stats?.documents !== undefined ? `${inspect.stats.documents} 篇文档` : '',
                inspect.include_secrets ? '含数据源密钥' : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          </Space>

          <Radio.Group
            value={mode}
            onChange={e => setMode(e.target.value as 'new' | 'restore')}
            style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}
          >
            <Radio value="new">导入为新工作区</Radio>
            {existing && (
              <Radio value="restore">
                覆盖恢复到已有工作区「{existing.name}」
                <Tag color="error" style={{ marginInlineStart: 8 }}>危险</Tag>
              </Radio>
            )}
          </Radio.Group>

          {mode === 'new' && (
            <div style={{ marginTop: 12 }}>
              <Input
                value={newName}
                maxLength={255}
                aria-label="新工作区名称"
                placeholder="新工作区名称（默认归档名 + 导入时间）"
                onChange={e => setNewName(e.target.value)}
              />
            </div>
          )}

          {mode === 'restore' && existing && (
            <div style={{ marginTop: 12 }}>
              <Alert
                type="error"
                showIcon
                icon={<WarningOutlined />}
                title="危险操作：覆盖恢复"
                description={`将清空「${existing.name}」现有业务数据并用归档全量重建，不可撤销。`}
                style={{ marginBottom: 12 }}
              />
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                <Checkbox
                  checked={confirmChecked}
                  onChange={e => setConfirmChecked(e.target.checked)}
                >我已知晓：恢复将清空该工作区现有全部业务数据，且不可撤销</Checkbox>
                <Input
                  placeholder={`输入工作区名称「${inspect.workspace_name}」以确认`}
                  value={confirmName}
                  onChange={e => setConfirmName(e.target.value)}
                />
              </Space>
            </div>
          )}
        </div>
      )}

      {importing && (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <Progress percent={100} status="active" showInfo={false} />
          <div style={{ marginTop: 8, color: 'var(--cn-text-secondary)' }}>
            {mode === 'restore' ? '正在覆盖恢复，请稍候...' : '正在导入新工作区，请稍候...'}
          </div>
        </div>
      )}

      {importResult && !importing && (
        <div style={{
          padding: 16,
          background: 'var(--cn-mix-green-10-bg-container)',
          borderRadius: 8,
          textAlign: 'center',
        }}>
          <FileTextOutlined style={{ color: '#22c55e', fontSize: 'var(--cn-text-xl)' }} />
          <span style={{ marginLeft: 8, color: '#15803d' }}>
            {mode === 'restore' ? '恢复完成' : '导入完成'}：{importResult.tables} 表 / {importResult.rows} 行
            / {importResult.views} 视图{importResult.documents ? ` / ${importResult.documents} 文档` : ''}
          </span>
        </div>
      )}
    </Modal>
  )
}

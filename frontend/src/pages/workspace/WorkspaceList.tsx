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
  Upload, Alert, Progress, Skeleton, Tooltip,
} from 'antd'
import {
  PlusOutlined, StarOutlined, StarFilled, CaretRightOutlined, TeamOutlined, TableOutlined,
  DownloadOutlined, SettingOutlined, SearchOutlined, GlobalOutlined, LockOutlined,
  SafetyCertificateOutlined, UploadOutlined, InboxOutlined, FileTextOutlined,
  FolderOpenOutlined, DatabaseOutlined, LoginOutlined, ArrowRightOutlined, HolderOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useResponsive } from '@/hooks/useResponsive'
import { usePreferences, useSetWorkspaceOrder } from '@/hooks/useFavoriteViews'
import { workspaceApi, tableApi } from '@/api'
import type {
  Workspace, WorkspaceRole, WorkspaceType, WorkspaceVisibility, TableSummary,
} from '@/api'
import {
  WORKSPACE_TYPE_HINT, WORKSPACE_TYPE_LABEL, WORKSPACE_TYPE_OPTIONS,
  workspaceLandingSegment, workspaceTypeFeatures,
} from '@/utils/workspaceType'
import { flattenWorkspaceOrder, sortWorkspaces } from '@/utils/homeOrder'
import WorkspaceSettingsModal from '@/pages/settings/WorkspaceSettingsModal'
import WorkspaceBackupDialog from '@/pages/settings/WorkspaceBackupDialog'
import MyViewsPanel from './MyViewsPanel'

const { Title, Text } = Typography

/** 工作区列表页携带统计信息的工作区视图模型 */
type WSWithStats = Workspace & {
  table_count?: number; member_count?: number;
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

/** 工作区类型徽标配色：标识功能范围（非权限），与公开性色系区分 */
const TYPE_TAG_COLOR: Record<WorkspaceType, string> = {
  data_doc: 'geekblue', data: 'purple', doc: 'orange',
}

/** 行首图标：按工作区类型区分数据 / 文档语义 */
const TYPE_ICON: Record<WorkspaceType, React.ReactNode> = {
  data_doc: <DatabaseOutlined />,
  data: <TableOutlined />,
  doc: <FileTextOutlined />,
}

/** 展开后速览的数据表数量上限（超出走「查看全部」，避免展开区无限长） */
const PREVIEW_TABLE_LIMIT = 8

/** 列表时间紧凑格式：`2026-10-18 20:19`（窄屏单行，不用 toLocaleString 的秒级长串） */
function formatListTime(value?: string): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function WorkspaceList() {
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState<Workspace | null>(null)
  const [backupOpen, setBackupOpen] = useState<Workspace | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [search, setSearch] = useState('')
  /** 已展开的工作区 id 集合（允许多行同时展开，与 GitHub 文件树一致） */
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [form] = Form.useForm()
  const [importForm] = Form.useForm()

  const { data: workspaces = [], isLoading } = useQuery<WSWithStats[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // 主页自定义顺序（ADR 0021）：偏好缺失 / 读取失败时按 pinned → id 兜底
  const { data: prefs } = usePreferences()
  const setWorkspaceOrder = useSetWorkspaceOrder()
  const workspaceDragSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  )

  const create = useMutation({
    mutationFn: (v: {
      name: string; description?: string;
      visibility?: WorkspaceVisibility; tags?: string[]; allow_edit?: boolean;
      workspace_type?: WorkspaceType;
    }) => workspaceApi.create({
      name: v.name,
      description: v.description ?? '',
      visibility: v.visibility ?? 'member',
      tags: v.tags ?? [],
      allow_edit: v.allow_edit ?? true,
      workspace_type: v.workspace_type ?? 'data_doc',
    }),
    onSuccess: (w) => {
      message.success(`已创建 "${w.name}"`)
      setCreateOpen(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/w/${w.id}/${workspaceLandingSegment(w.workspace_type)}`)
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

  // 排序（pinned 分组优先 → 自定义顺序 → id）+ 搜索过滤
  const filteredWorkspaces = useMemo(() => {
    const ordered = sortWorkspaces(workspaces, prefs?.workspace_order)
    const q = search.trim().toLowerCase()
    if (!q) return ordered
    return ordered.filter(w =>
      (w.name ?? '').toLowerCase().includes(q) ||
      (w.description ?? '').toLowerCase().includes(q) ||
      (w.tags ?? []).some(t => t.toLowerCase().includes(q)),
    )
  }, [workspaces, search, prefs?.workspace_order])

  const starred = filteredWorkspaces.filter(w => w.pinned)
  const others = filteredWorkspaces.filter(w => !w.pinned)
  /** 搜索过滤时禁止拖拽：保存的是当前展示顺序，只提交过滤子集会误伤未展示工作区的名次 */
  const dragEnabled = !search.trim()

  /** 组内拖拽结束：跨分组不生效；保存时按展示顺序扁平化「已收藏组 + 其他组」 */
  const handleWorkspaceDragEnd = (event: DragEndEvent) => {
    if (!dragEnabled) return
    const { active, over } = event
    if (!over || active.id === over.id) return
    const byId = new Map(workspaces.map(w => [String(w.id), w]))
    const activeWs = byId.get(String(active.id))
    const overWs = byId.get(String(over.id))
    if (!activeWs || !overWs || !!activeWs.pinned !== !!overWs.pinned) return

    const group = activeWs.pinned ? starred : others
    const groupIds = group.map(w => String(w.id))
    const from = groupIds.indexOf(String(active.id))
    const to = groupIds.indexOf(String(over.id))
    if (from < 0 || to < 0) return
    const nextGroup = arrayMove(groupIds, from, to)
    const starredIds = activeWs.pinned ? nextGroup : starred.map(w => String(w.id))
    const otherIds = activeWs.pinned ? others.map(w => String(w.id)) : nextGroup
    setWorkspaceOrder.mutate(flattenWorkspaceOrder(starredIds, otherIds), {
      onError: (err) => message.error(err instanceof Error ? err.message : '保存排序失败，请重试'),
    })
  }

  /** 行渲染：拖拽把手 + 收起态图标 + 展开详情（拖拽只在把手生效） */
  const renderRow = (w: WSWithStats) => (
    <WorkspaceRow
      key={w.id}
      ws={w}
      expanded={expandedIds.has(String(w.id))}
      draggable={dragEnabled}
      isMobile={isMobile}
      onToggle={() => toggleExpand(w.id)}
      onPin={() => pin.mutate(w)}
      onSettings={() => setSettingsOpen(w)}
      onBackup={() => setBackupOpen(w)}
    />
  )

  return (
    <div style={{ padding: isMobile ? 12 : 16 }} data-testid="workspace-list">
      {/* 左右双板块：左侧「我的工作区」卡片（标题 + 搜索 + 新建/导入 + 列表）与右侧「我的视图」卡片同高 */}
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
              <Text type="secondary">选择或创建一个工作区开始协作</Text>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Input.Search
                placeholder="搜索工作区名称/标签..."
                allowClear
                prefix={<SearchOutlined />}
                style={{ width: isMobile ? '100%' : 260 }}
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setCreateOpen(true)}
                style={isMobile ? { flex: 1 } : undefined}
                data-testid="create-workspace-btn"
              >
                新建工作区
              </Button>
              <Button
                icon={<UploadOutlined />}
                onClick={() => { importForm.resetFields(); setImportOpen(true) }}
                style={isMobile ? { flex: 1 } : undefined}
                data-testid="import-workspace-btn"
              >
                导入工作区
              </Button>
            </div>
          </div>

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
            <Empty description={search ? `没有匹配「${search}」的工作区` : '还没有工作区，创建一个吧！'} />
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
                      <span>已收藏</span>
                      <span className="cn-ws-group-count">{starred.length}</span>
                    </div>
                    <SortableContext
                      items={starred.map(w => String(w.id))}
                      strategy={verticalListSortingStrategy}
                    >
                      <div className="cn-ws-list">{starred.map(renderRow)}</div>
                    </SortableContext>
                  </section>
                )}
                {others.length > 0 && (
                  <section className="cn-ws-group" data-testid="workspace-group-others">
                    {starred.length > 0 && (
                      <div className="cn-ws-group-head">
                        <span>其他工作区</span>
                        <span className="cn-ws-group-count">{others.length}</span>
                      </div>
                    )}
                    <SortableContext
                      items={others.map(w => String(w.id))}
                      strategy={verticalListSortingStrategy}
                    >
                      <div className="cn-ws-list">{others.map(renderRow)}</div>
                    </SortableContext>
                  </section>
                )}
              </div>
            </DndContext>
          )}
        </div>

        {/* 右侧「我的视图」：桌面固定宽分栏，<992px 由 CSS 堆叠到工作区下方 */}
        <aside className="cn-home-aside" data-testid="workspace-home-aside">
          <MyViewsPanel />
        </aside>
      </div>

      {/* 新建工作区 Modal — 扩展字段；条件渲染避免 Form.useForm 在未挂载时触发 warning */}
      {createOpen && (
        <Modal
          title="新建工作区"
          open={createOpen}
          onCancel={() => { form.resetFields(); setCreateOpen(false) }}
          onOk={() => form.submit()}
          confirmLoading={create.isPending}
          okText="创建"
          data-testid="create-workspace-modal"
          width={isMobile ? 'calc(100vw - 32px)' : 520}
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={{ visibility: 'member', allow_edit: true, workspace_type: 'data_doc' }}
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
              name="workspace_type"
              label="工作区类型"
              extra={WORKSPACE_TYPE_HINT[(form.getFieldValue('workspace_type') as WorkspaceType) ?? 'data_doc']}
            >
              <Select options={WORKSPACE_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="visibility" label="公开性">
              <Select
                options={[
                  { value: 'public', label: '公开（任何人可读）' },
                  { value: 'member', label: '成员可见（推荐）' },
                  { value: 'private', label: '私有（仅所有者/管理员）' },
                ]}
              />
            </Form.Item>
            <Form.Item name="tags" label="标签（逗号分隔，可选）">
              <Input placeholder="例如：研发, 产品, 核心业务" />
            </Form.Item>
            <Form.Item name="allow_edit" label="允许成员编辑数据" valuePropName="checked">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Switch />
                <span style={{ color: '#64748b', fontSize: 13 }}>
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

      {/* 导入工作区 Modal — 从备份 JSON 创建全新工作区 */}
      {importOpen && <ImportWorkspaceModal
        open={importOpen}
        form={importForm}
        onCancel={() => setImportOpen(false)}
        onSuccess={(w) => {
          setImportOpen(false)
          queryClient.invalidateQueries({ queryKey: ['workspaces'] })
          message.success(`已导入工作区「${w.name}」`)
          navigate(`/w/${w.id}/${workspaceLandingSegment(w.workspace_type)}`)
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
  ws, expanded, draggable, isMobile, onToggle, onPin, onSettings, onBackup,
}: {
  ws: WSWithStats
  expanded: boolean
  draggable: boolean
  isMobile: boolean
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
  const type = (ws.workspace_type ?? 'data_doc') as WorkspaceType
  const landing = `/w/${ws.id}/${workspaceLandingSegment(type)}`

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

        <span className="cn-ws-row-icon" aria-hidden>{TYPE_ICON[type]}</span>

        <div className="cn-ws-row-title">
          <span className="cn-ws-row-name" title={ws.name}>{ws.name}</span>
          <Tooltip title={vis.label}>
            <span className="cn-ws-row-vis" style={{ color: 'var(--cn-text-muted)' }} aria-label={vis.label}>
              {vis.icon}
            </span>
          </Tooltip>
          <Tag color={TYPE_TAG_COLOR[type]} className="cn-ws-row-tag">
            {WORKSPACE_TYPE_LABEL[type]}
          </Tag>
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
              <span className="cn-ws-row-time">{formatListTime(ws.updated_at)}</span>
            )}
          </div>
        )}

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
  const features = workspaceTypeFeatures(ws.workspace_type)

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

      {tags.length > 0 && (
        <div className="cn-ws-detail-tags">
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
            <Text type="secondary" style={{ fontSize: 12 }}>还没有数据表</Text>
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

/** 允许导入的文件扩展名 */
const ACCEPTED_BACKUP_EXT = ['.json']

interface ImportWorkspaceModalProps {
  open: boolean
  form: ReturnType<typeof Form.useForm>[0]
  onCancel: () => void
  onSuccess: (w: Workspace) => void
  onError: (err: unknown) => void
}

function ImportWorkspaceModal({ open, form, onCancel, onSuccess, onError }: ImportWorkspaceModalProps) {
  const { isMobile } = useResponsive()
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ tables: number; rows: number; views: number; documents: number } | null>(null)
  const [pendingJson, setPendingJson] = useState<Record<string, unknown> | null>(null)

  const reset = () => {
    setImportResult(null)
    setPendingJson(null)
    form.resetFields()
  }

  const beforeUpload = async (file: File) => {
    const name = file.name.toLowerCase()
    if (!ACCEPTED_BACKUP_EXT.some(ext => name.endsWith(ext))) {
      onError(new Error('仅支持 JSON 备份文件'))
      return false
    }
    try {
      const text = await file.text()
      const json = JSON.parse(text)
      setPendingJson(json)
      setImportResult(null)
      // 自动从备份文件里的 workspace.name 填充工作区名称
      const wsMeta = (json as Record<string, any>).workspace
      if (wsMeta?.name) {
        form.setFieldsValue({ name: wsMeta.name })
      }
    } catch {
      onError(new Error('文件内容不是有效的 JSON'))
    }
    // 返回 false 阻止 Upload 组件自动上传，手动在 onOk 里提交
    return false
  }

  const handleSubmit = async () => {
    if (!pendingJson) {
      onError(new Error('请先选择备份文件'))
      return
    }
    const raw: unknown = await form.validateFields().catch(() => null)
    if (!raw) return
    const values = raw as { name?: string }

    try {
      setImporting(true)
      const result = await workspaceApi.importFromBackup({
        name: values.name,
        json_data: pendingJson,
      })
      setImportResult({
        tables: result.imported_tables,
        rows: result.imported_rows,
        views: result.imported_views,
        documents: result.imported_documents ?? 0,
      })
      // 延迟一下让用户看到成功信息，然后跳转
      setTimeout(() => onSuccess(result.workspace), 800)
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
      okText="开始导入"
      cancelText="取消"
      destroyOnHidden
      width={isMobile ? 'calc(100vw - 32px)' : 560}
    >
      <Alert
        type="info"
        showIcon
        message="从备份 JSON 创建一个全新的工作区"
        description="备份文件中的表结构、数据行和视图都会一并导入，当前用户自动成为该工作区所有者。"
        style={{ marginBottom: 16 }}
      />

      {!importResult && (
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="工作区名称（可修改）">
            <Input placeholder="默认使用备份文件中的工作区名称" />
          </Form.Item>

          <div style={{ marginBottom: 16 }}>
            <Upload.Dragger
              multiple={false}
              accept={ACCEPTED_BACKUP_EXT.join(',')}
              beforeUpload={beforeUpload}
              disabled={importing}
              showUploadList={false}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽 JSON 备份文件到此处</p>
              <p className="ant-upload-hint">从其他工作区导出的 JSON 备份文件</p>
            </Upload.Dragger>
          </div>
        </Form>
      )}

      {importing && (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <Progress percent={100} status="active" showInfo={false} />
          <div style={{ marginTop: 8, color: '#64748b' }}>正在导入，请稍候...</div>
        </div>
      )}

      {importResult && !importing && (
        <div style={{
          padding: 16,
          background: 'var(--cn-mix-green-10-bg-container)',
          borderRadius: 8,
          textAlign: 'center',
        }}>
          <FileTextOutlined style={{ color: '#22c55e', fontSize: 20 }} />
          <span style={{ marginLeft: 8, color: '#15803d' }}>
            导入完成：{importResult.tables} 表 / {importResult.rows} 行 / {importResult.views} 视图{importResult.documents ? ` / ${importResult.documents} 文档` : ''}
          </span>
        </div>
      )}
    </Modal>
  )
}

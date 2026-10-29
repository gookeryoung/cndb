/** 工作区表列表页 — 数据表目录视图.
 *
 * 支持创建/重命名/复制/删除 + CSV 自动建表 + API 自动建表 + 拖拽排序.
 * 展示 Owner / MyAccess / MemberCount 三个权限元信息列, 并提供按访问级别筛选.
 */

import { Suspense, createContext, lazy, useCallback, useContext, useMemo, useState } from 'react'
import {
  Button, Modal, Form, Input, Table, Typography, Empty, App as AntApp, Space, Tag, Upload, Dropdown,
  Avatar, Segmented, Badge, Tooltip,
} from 'antd'
import type { MenuProps } from 'antd'
import {
  PlusOutlined, TableOutlined, DeleteOutlined, ClockCircleOutlined, CopyOutlined, EditOutlined,
  UploadOutlined, ApiOutlined, TeamOutlined, UserOutlined,
  LoginOutlined, MoreOutlined, HolderOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import {
  DndContext, DragEndEvent, KeyboardSensor, PointerSensor, TouchSensor, closestCenter,
  useSensor, useSensors,
} from '@dnd-kit/core'
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core'
import {
  SortableContext, verticalListSortingStrategy, useSortable, arrayMove, sortableKeyboardCoordinates,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { tableApi, workspaceApi, importApi } from '@/api'
import type { TableSummary, TableUpdate, FileAnalyzeResult } from '@/api'
import { useAuthStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'
import { useCreateParam } from '@/hooks/useCreateParam'
import { WEIGHT } from '@/theme/tokens'

const ApiImportDialog = lazy(() => import('@/pages/import-export/ApiImportDialog'))

/** 表级读取门槛的角色文案（用于「受限」提示） */
const READ_ROLE_LABEL: Record<string, string> = {
  viewer: '普通成员',
  editor: '编辑者',
  owner: '所有者',
}
const FileImportPreview = lazy(() => import('@/pages/import-export/FileImportPreview'))

const { Title, Text } = Typography

/** 列表时间紧凑格式：`2026-10-18 20:19`
 *
 * 不用 `toLocaleString()`：中文本地化会带秒（19 字符）+ 窄列宽下被挤成两行，
 * 把整行行高翻倍。等宽数字 + 短格式才能在 150px 内单行放完。 */
function formatListTime(value?: string): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 悬停提示用的完整时间（含秒） */
function formatFullTime(value?: string): string {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

type AccessFilter = 'all' | 'owner' | 'write' | 'read'

const ACCESS_TAG: Record<string, { color: string; label: string }> = {
  owner: { color: 'red', label: 'owner' },
  write: { color: 'green', label: 'write' },
  read: { color: 'blue', label: 'read' },
  none: { color: 'default', label: '默认' },
}

/** 拖拽把手的控制对象 —— 由行/卡片组件通过 context 下发，避免整行可拖与「点击进表」抢手势. */
type DragHandleState = {
  attributes: DraggableAttributes
  listeners?: DraggableSyntheticListeners
  setActivatorNodeRef?: (node: HTMLElement | null) => void
}

const DragHandleContext = createContext<DragHandleState | null>(null)

/** AntD Table 可拖拽行 —— 配合 DndContext + SortableContext 使用.
 *
 * 行本身只接管 transform / 拖拽态样式，拖动仅由把手（DragHandle）激活：
 * 此前 listeners 挂整行，按下即开始拖动，导致「点一下进表」与拖动互相抢手势。
 */
function DraggableRow({
  style,
  ...rest
}: React.HTMLAttributes<HTMLTableRowElement>) {
  // 从 data-row-key 读取排序 id（AntD Table 自动传入），统一转 string 与 SortableContext items 对齐
  const rowKey = String((rest as Record<string, unknown>)['data-row-key'])
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: rowKey })
  return (
    <DragHandleContext.Provider value={{ attributes, listeners, setActivatorNodeRef }}>
      <tr
        ref={setNodeRef}
        style={{
          ...style,
          transform: CSS.Transform.toString(transform),
          transition,
          opacity: isDragging ? 0.6 : undefined,
        }}
        data-dragging={isDragging ? 'true' : undefined}
        {...rest}
      />
    </DragHandleContext.Provider>
  )
}

/** 排序把手：桌面表格行与窄屏卡片共用.
 *
 * 键盘可用（Space 提起 / ↑↓ 移动 / Space 放下），也是 e2e 与单测唯一可靠的拖拽入口。
 */
function DragHandle({ enabled, testId }: { enabled: boolean; testId: string }) {
  const ctx = useContext(DragHandleContext)
  // 无排序权限（只读角色）时保留占位，避免列宽抖动
  if (!enabled || !ctx) return <span aria-hidden style={{ display: 'inline-block', width: 16 }} />
  return (
    <Tooltip title="上下拖动调整顺序（松手即保存）">
      <span
        ref={ctx.setActivatorNodeRef}
        data-testid={testId}
        {...ctx.attributes}
        {...ctx.listeners}
        aria-label="拖动调整数据表顺序"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          cursor: 'grab',
          color: 'var(--cn-text-muted)',
          // 触摸设备上把手手势不参与页面滚动，否则按住就滚走了
          touchAction: 'none',
        }}
      >
        <HolderOutlined />
      </span>
    </Tooltip>
  )
}

/** 窄屏卡片：一屏一表，把手在卡片头右侧，点击卡身进表. */
function SortableTableCard({
  record,
  canReorder,
  menu,
  onOpen,
  onPrefetch,
}: {
  record: TableSummary
  canReorder: boolean
  menu: MenuProps['items']
  onOpen: () => void
  onPrefetch: () => void
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: String(record.id) })
  const access = ACCESS_TAG[record.my_access ?? 'none'] ?? ACCESS_TAG.none
  return (
    <DragHandleContext.Provider value={{ attributes, listeners, setActivatorNodeRef }}>
      <div
        ref={setNodeRef}
        className="cn-table-list-card"
        data-testid={`table-card-${record.id}`}
        style={{
          transform: CSS.Transform.toString(transform),
          transition,
          opacity: isDragging ? 0.6 : undefined,
          boxShadow: isDragging ? '0 8px 20px rgba(0, 0, 0, 0.16)' : undefined,
          position: 'relative',
          zIndex: isDragging ? 2 : undefined,
        }}
        onClick={onOpen}
        onMouseEnter={onPrefetch}
      >
        <div className="cn-table-list-card-head">
          <TableOutlined style={{ color: '#3b82f6' }} />
          <span className="cn-table-list-card-name">{record.name}</span>
          <Tag color={access.color} style={{ marginInlineEnd: 0 }}>{access.label}</Tag>
          <DragHandle enabled={canReorder} testId={`table-drag-${record.id}`} />
        </div>
        {record.description && <div className="cn-table-list-card-desc">{record.description}</div>}
        <div className="cn-table-list-card-meta">
          <span>{record.record_count ?? 0} 条记录 · {record.field_count ?? 0} 字段 · {record.member_count ?? 0} 成员</span>
          {record.updated_at && <span>更新于 {formatListTime(record.updated_at)}</span>}
        </div>
        <div className="cn-table-list-card-actions">
          <Button size="small" type="link" icon={<LoginOutlined />} data-testid={`open-table-${record.id}`}>打开</Button>
          {/* 触摸设备没有 hover，卡片内菜单用 click 触发 */}
          <Dropdown trigger={['click']} menu={{ items: menu }}>
            <Button
              type="text"
              size="small"
              icon={<MoreOutlined />}
              onClick={(e) => e.stopPropagation()}
              data-testid={`more-table-${record.id}`}
            />
          </Dropdown>
        </div>
      </div>
    </DragHandleContext.Provider>
  )
}

export default function TablesList() {
  const { message, modal } = AntApp.useApp()
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuthStore(s => s.user)
  const { isMobile } = useResponsive()
  const [createOpen, setCreateOpen] = useState(false)
  // 命令面板「新建数据表」经 URL ?create=1 触发（0067 C3）
  useCreateParam(() => setCreateOpen(true))
  const [editOpen, setEditOpen] = useState<TableSummary | null>(null)
  const [apiImportOpen, setApiImportOpen] = useState(false)
  const [filter, setFilter] = useState<AccessFilter>('all')
  // 文件导入预览 Modal 状态
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const [previewAnalyze, setPreviewAnalyze] = useState<FileAnalyzeResult | null>(null)
  const [analyzingFile, setAnalyzingFile] = useState(false)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  // workspace 信息（标题展示）
  const { data: workspace } = useQuery({
    queryKey: ['workspaces', wid],
    queryFn: () => workspaceApi.get(wid!),
    enabled: !!wid,
  })

  // 表列表
  const { data: tables = [], isLoading } = useQuery<TableSummary[]>({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid!),
    enabled: !!wid,
  })

  /** hover 预取表详情 —— 点击进表时 useTable 命中缓存，减少冷启动白屏（queryKey 与 useTable 一致）. */
  const prefetchTable = useCallback((targetTid: string | number) => {
    if (!wid) return
    void queryClient.prefetchQuery({
      queryKey: ['table', `${wid}/${targetTid}`],
      queryFn: () => tableApi.get(wid, String(targetTid)),
      staleTime: 60_000,
    })
  }, [wid, queryClient])

  // ── 筛选后的表列表 ──
  const filteredTables = useMemo(() => {
    if (filter === 'all') return tables
    return tables.filter(t => {
      const access = t.my_access ?? 'none'
      // "我拥有的" 同时也包含显式标记为 owner 的表
      if (filter === 'owner') {
        if (access === 'owner') return true
        // 后端若没返回 my_access, 回退到比对 owner.id
        if (access === 'none' && t.owner && user) return String(t.owner.id) === String(user.id)
        return false
      }
      if (filter === 'write') return access === 'write' || access === 'owner'
      if (filter === 'read') return access === 'read' || access === 'write' || access === 'owner'
      return true
    })
  }, [tables, filter, user])

  const create = useMutation({
    mutationFn: (v: { name: string; description?: string }) => tableApi.create(wid!, v),
    onSuccess: (t) => {
      message.success(`已创建表 "${t.name}"`)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
      setCreateOpen(false)
      form.resetFields()
      navigate(`/w/${wid}/tables/${t.id}`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建表失败'),
  })

  const update = useMutation({
    mutationFn: ({ tid, data }: { tid: number | string; data: TableUpdate }) => tableApi.update(wid!, tid, data),
    onSuccess: () => {
      message.success('已更新')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      setEditOpen(null)
      editForm.resetFields()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新表失败'),
  })

  const copy = useMutation({
    mutationFn: (args: { tid: number | string; mode: 'structure' | 'all' }) =>
      tableApi.copy(wid!, args.tid, { mode: args.mode }),
    onSuccess: (t, args) => {
      const modeLabel = args.mode === 'all' ? '(含全部数据)' : '(仅结构)'
      message.success(`已复制为 "${t.name}" ${modeLabel}`)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '复制表失败'),
  })

  const remove = useMutation({
    mutationFn: (tid: number | string) => tableApi.remove(wid!, tid),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除表失败'),
  })

  // ── 表顺序拖拽 ──
  // 桌面用指针（移动 4px 才激活，避免误触）；触摸端用长按（180ms）激活，
  // 且只有把手带 touch-action: none，不会与页面滚动抢手势。
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  // 只有 owner / editor 能改顺序（后端 reorder 要求 EDITOR 及以上）
  const canReorder = workspace?.current_user_role !== 'viewer'
  const reorderTables = useMutation({
    mutationFn: (ids: Array<number | string>) => tableApi.reorder(wid!, ids),
    // 乐观重排：不先动本地列表的话，请求返回前松手的那一行会「弹回原位」，
    // 看起来像没生效；失败时用快照回滚。
    onMutate: async (ids) => {
      const key = ['workspaces', wid, 'tables']
      await queryClient.cancelQueries({ queryKey: key })
      const prev = queryClient.getQueryData<TableSummary[]>(key)
      if (prev) {
        const byId = new Map(prev.map(t => [String(t.id), t]))
        const next = ids
          .map(id => byId.get(String(id)))
          .filter((t): t is TableSummary => !!t)
        // 提交序列可能不含全部表（并发新增等），缺失的按原顺序补到尾部，避免本地丢行
        prev.forEach(t => { if (!ids.map(String).includes(String(t.id))) next.push(t) })
        queryClient.setQueryData(key, next)
      }
      return { prev }
    },
    onError: (err, _ids, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['workspaces', wid, 'tables'], ctx.prev)
      message.error(err instanceof Error ? err.message : '排序失败')
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
    },
  })
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    // 定位必须在**可见列表**里做：筛选态下 filteredTables 与 tables 的索引不同，
    // 用全量索引换位置会把表错插到别的筛选档位里。
    const oldIndex = filteredTables.findIndex(t => String(t.id) === String(active.id))
    const newIndex = filteredTables.findIndex(t => String(t.id) === String(over.id))
    if (oldIndex < 0 || newIndex < 0) return
    const moved = arrayMove(filteredTables, oldIndex, newIndex)
    // 合并回全量序列：未命中筛选的表保持原位，命中表按新顺序依次填空
    const visibleSet = new Set(filteredTables.map(t => String(t.id)))
    let cursor = 0
    const merged = tables.map(t => (visibleSet.has(String(t.id)) ? moved[cursor++].id : t.id))
    if (merged.every((id, i) => String(id) === String(tables[i].id))) return
    reorderTables.mutate(merged)
  }

  /** 表行操作菜单（表格操作列与窄屏卡片共用一套入口） */
  const buildTableMenu = (record: TableSummary) => [
    {
      key: 'rename',
      icon: <EditOutlined />,
      label: '重命名/编辑',
      onClick: (e?: { domEvent?: { stopPropagation?: () => void } }) => {
        e?.domEvent?.stopPropagation?.()
        setEditOpen(record)
        editForm.setFieldsValue({ name: record.name, description: record.description })
      },
    },
    {
      key: 'copy',
      icon: <CopyOutlined />,
      label: '复制表',
      children: [
        {
          key: 'copy-structure',
          label: '仅复制表结构',
          onClick: (e?: { domEvent?: { stopPropagation?: () => void } }) => {
            e?.domEvent?.stopPropagation?.()
            copy.mutate({ tid: record.id, mode: 'structure' })
          },
        },
        {
          key: 'copy-all',
          label: '复制表结构 + 全部数据',
          onClick: (e?: { domEvent?: { stopPropagation?: () => void } }) => {
            e?.domEvent?.stopPropagation?.()
            copy.mutate({ tid: record.id, mode: 'all' })
          },
        },
      ],
    },
    { type: 'divider' as const },
    {
      key: 'delete',
      icon: <DeleteOutlined />,
      label: '删除表',
      danger: true,
      onClick: (e?: { domEvent?: { stopPropagation?: () => void } }) => {
        e?.domEvent?.stopPropagation?.()
        modal.confirm({
          title: `删除表「${record.name}」？`,
          content: '表内所有记录和字段将被永久移除。',
          okText: '删除',
          okType: 'danger',
          cancelText: '取消',
          onOk: () => remove.mutate(record.id),
        })
      },
    },
  ]

  const columns = [
    {
      title: '',
      key: 'drag',
      width: 36,
      render: (_: unknown, record: TableSummary) => (
        <DragHandle enabled={canReorder} testId={`table-drag-${record.id}`} />
      ),
    },
    {
      title: '表名',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: TableSummary) => (
        <span>
          <a onClick={() => navigate(`/w/${wid}/tables/${record.id}`)} style={{ fontWeight: WEIGHT.medium }}>
            <TableOutlined style={{ marginRight: 8, color: '#3b82f6' }} />
            {name}
          </a>
          {/* 受限提示：普通成员看不到这张表；能让管理员知道"为什么别人说找不到" */}
          {record.is_restricted && (
            <Tooltip
              title={`读取门槛：${READ_ROLE_LABEL[record.read_role ?? ''] ?? record.read_role ?? '自定义'}及以上；普通成员不可见`}
            >
              <Tag
                color="orange"
                data-testid={`table-restricted-${record.id}`}
                style={{ marginLeft: 8, fontSize: 11, lineHeight: '16px' }}
              >
                受限
              </Tag>
            </Tooltip>
          )}
        </span>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (d?: string) => d ? <Text type="secondary">{d}</Text> : <Text type="secondary" italic>—</Text>,
    },
    {
      title: '拥有者',
      dataIndex: 'owner',
      key: 'owner',
      width: 144,
      render: (owner?: { id: number | string; username: string } | null) => {
        if (!owner) {
          return <Text type="secondary">未指定</Text>
        }
        const isMe = user && String(owner.id) === String(user.id)
        return (
          <Space size={6}>
            <Avatar size="small" icon={<UserOutlined />} />
            <span>
              {owner.username}
              {isMe && <Tag color="red" style={{ marginLeft: 4, fontSize: 11, lineHeight: '16px' }}>我</Tag>}
            </span>
          </Space>
        )
      },
    },
    {
      title: '我的访问',
      dataIndex: 'my_access',
      key: 'my_access',
      width: 92,
      render: (access?: string) => {
        const key = access ?? 'none'
        const info = ACCESS_TAG[key] ?? ACCESS_TAG.none
        return <Tag color={info.color}>{info.label}</Tag>
      },
    },
    {
      title: '成员数',
      dataIndex: 'member_count',
      key: 'member_count',
      width: 80,
      align: 'right' as const,
      render: (n?: number) => (
        <Tooltip title="显式授权成员：在表设置中单独授权的成员数量（未显式授权时遵循工作区角色）">
          <Badge
            count={n ?? 0}
            showZero
            overflowCount={99}
            size="small"
            color={(n ?? 0) > 0 ? 'var(--cn-brand-color)' : undefined}
          >
            <TeamOutlined style={{ fontSize: 16, color: 'var(--cn-text-muted)' }} />
          </Badge>
        </Tooltip>
      ),
    },
    {
      title: '字段',
      dataIndex: 'field_count',
      key: 'field_count',
      width: 62,
      align: 'right' as const,
      render: (n?: number) => <Tag>{n ?? 0}</Tag>,
    },
    {
      title: '记录',
      dataIndex: 'record_count',
      key: 'record_count',
      width: 72,
      align: 'right' as const,
      render: (n?: number) => <Text>{n ?? 0}</Text>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      // 固定 nowrap + 短格式：宽 170 时 toLocaleString() 带秒会折成两行，行高翻倍
      width: 148,
      render: (t?: string) => t ? (
        <Tooltip title={formatFullTime(t)}>
          <Text
            type="secondary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              whiteSpace: 'nowrap',
              fontSize: 12,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            <ClockCircleOutlined />
            {formatListTime(t)}
          </Text>
        </Tooltip>
      ) : <Text type="secondary">—</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 96,
      render: (_: unknown, record: TableSummary) => (
        <Space size="small">
          <Tooltip title="打开这张表，进入数据表格页">
            <Button
              type="text"
              size="small"
              icon={<LoginOutlined />}
              onClick={(e) => { e.stopPropagation(); navigate(`/w/${wid}/tables/${record.id}`) }}
              data-testid={`open-table-${record.id}`}
            />
          </Tooltip>
          <Dropdown menu={{ items: buildTableMenu(record) }}>
            <Tooltip title="更多操作：重命名、复制表、删除表">
              <Button
                type="text"
                size="small"
                icon={<MoreOutlined />}
                onClick={(e) => e.stopPropagation()}
                data-testid={`more-table-${record.id}`}
              />
            </Tooltip>
          </Dropdown>
        </Space>
      ),
    },
  ]

  // 移动端裁剪次要列：仅保留 表名 / 我的访问 / 记录 / 操作，减少横向滚动成本；
  // 桌面端保持全列（含拖拽把手、描述、拥有者、更新时间等）。
  const visibleColumns = isMobile
    ? columns.filter(c => ['name', 'my_access', 'record_count', 'actions'].includes(String(c.key)))
    : columns

  return (
    <div style={{ padding: isMobile ? 12 : 16 }}>
      {/* Header —— 移动端标题与按钮区自动换行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <DatabaseOutlined style={{ marginRight: 8 }} />
            {workspace?.name ? `${workspace.name} · 数据表` : '数据表目录'}
          </Title>
          <Text type="secondary">
            {workspace?.description || '管理当前工作区的所有数据表'}
          </Text>
        </div>
        <Space wrap>
          <Upload
            accept=".csv,.tsv,.json,.xlsx"
            showUploadList={false}
            beforeUpload={async (file) => {
              setAnalyzingFile(true)
              try {
                const result = await importApi.analyzeFile(wid!, file as File)
                setPreviewFile(file as File)
                setPreviewAnalyze(result)
                setPreviewOpen(true)
              } catch (err) {
                message.error(err instanceof Error ? err.message : '文件解析失败')
              } finally {
                setAnalyzingFile(false)
              }
              return false  // 阻止 Upload 自动上传，由我们手动控制
            }}
          >
            <Button icon={<UploadOutlined />} loading={analyzingFile}>
              导入数据表
            </Button>
          </Upload>
          <Button
            icon={<ApiOutlined />}
            onClick={() => setApiImportOpen(true)}
            data-testid="api-import-entry"
          >
            API 建表
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新建表
          </Button>
        </Space>
      </div>

      {/* Filter Segmented —— 移动端纵向堆叠：筛选器整行、计数文本独立一行不折行 */}
      <div style={{
        marginBottom: 10,
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        justifyContent: 'space-between',
        alignItems: isMobile ? 'stretch' : 'center',
        flexWrap: 'wrap',
        gap: 8,
      }}>
        <Segmented<AccessFilter>
          block={isMobile}
          value={filter}
          onChange={(v) => setFilter(v as AccessFilter)}
          options={[
            // 窄屏 block 分段控件每项只有约 90px，长文案会被截断成「我可编…」
            { label: '全部', value: 'all' },
            { label: isMobile ? '我拥有' : '我拥有的', value: 'owner' },
            { label: isMobile ? '可编辑' : '我可编辑的', value: 'write' },
            { label: isMobile ? '可读' : '我可读的', value: 'read' },
          ]}
        />
        <Text
          type="secondary"
          style={{ whiteSpace: 'nowrap', marginLeft: isMobile ? 0 : 8, alignSelf: isMobile ? 'flex-start' : undefined }}
        >
          共 {filteredTables.length} / {tables.length} 张表
        </Text>
      </div>

      {/* Table 列表 —— 支持拖拽排序；卡片化容器与 Grid 工作台同构 */}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext
          items={filteredTables.map(t => String(t.id))}
          strategy={verticalListSortingStrategy}
        >
          {isMobile ? (
            /* 窄屏卡片列表：一屏一表，表名/描述/记录·字段·成员/更新时间/操作同卡片可见；
               排序入口为卡片头右侧把手（长按拖动），卡身点击仍是进表 */
            <div className="cn-table-list-cards" data-testid="tables-mobile-list">
              {filteredTables.length === 0 ? (
                <Empty
                  description={filter !== 'all' ? '当前筛选条件下没有表' : '还没有表 —— 点击「新建表」或「导入数据表」开始'}
                  style={{ padding: 32 }}
                />
              ) : filteredTables.map(record => (
                <SortableTableCard
                  key={record.id}
                  record={record}
                  canReorder={canReorder}
                  menu={buildTableMenu(record)}
                  onOpen={() => navigate(`/w/${wid}/tables/${record.id}`)}
                  onPrefetch={() => prefetchTable(record.id)}
                />
              ))}
            </div>
          ) : (
          <div className="cn-grid-card">
            <Table
              size="small"
              className="cn-table-list"
              loading={isLoading}
              rowKey="id"
              columns={visibleColumns}
              dataSource={filteredTables}
              pagination={false}
              scroll={{ x: 'max-content' }}
              components={{ body: { row: DraggableRow } }}
              onRow={(record) => ({
                onClick: () => navigate(`/w/${wid}/tables/${record.id}`),
                onMouseEnter: () => prefetchTable(record.id),
                'data-testid': `table-row-${record.id}`,
              })}
              locale={{
                emptyText: (
                  <Empty
                    description={
                      <span>
                        {filter !== 'all' ? '当前筛选条件下没有表' : (
                          <>
                            还没有表 —— 点击右侧 <Text strong>&quot;新建表&quot;</Text> 或 <Text strong>&quot;导入数据表&quot;</Text> 开始
                          </>
                        )}
                      </span>
                    }
                  />
                ),
              }}
            />
          </div>
          )}
        </SortableContext>
      </DndContext>

      {/* 创建 Modal */}
      <Modal
        title="新建表"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        okText="创建"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          onFinish={(v) => create.mutate(v)}
        >
          <Form.Item
            name="name"
            label="表名"
            rules={[
              { required: true, message: '请输入表名' },
              { max: 64, message: '表名不超过 64 字符' },
            ]}
          >
            <Input autoFocus placeholder="例如：客户信息、订单记录" maxLength={64} showCount />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} placeholder="简要说明这张表的用途" maxLength={255} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑表 Modal */}
      <Modal
        title="编辑表"
        open={!!editOpen}
        onCancel={() => { setEditOpen(null); editForm.resetFields() }}
        onOk={() => editForm.submit()}
        confirmLoading={update.isPending}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={editForm}
          layout="vertical"
          preserve={false}
          onFinish={(v) => {
            if (editOpen) {
              update.mutate({ tid: editOpen.id, data: v })
            }
          }}
        >
          <Form.Item
            name="name"
            label="表名"
            rules={[
              { required: true, message: '请输入表名' },
              { max: 64, message: '表名不超过 64 字符' },
            ]}
          >
            <Input maxLength={64} showCount />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} maxLength={255} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* API 建表 Dialog（建表模式） */}
      <Suspense fallback={null}>
        <ApiImportDialog
          open={apiImportOpen}
          wid={wid!}
          onClose={() => setApiImportOpen(false)}
          onSuccess={(res) => {
            if (res.table_id) {
              navigate(`/w/${wid}/tables/${res.table_id}`)
            }
          }}
        />
      </Suspense>

      {/* 文件导入预览 Modal */}
      <Suspense fallback={null}>
        <FileImportPreview
          open={previewOpen}
          wid={wid!}
          file={previewFile}
          analyzeResult={previewAnalyze}
          onClose={() => {
            setPreviewOpen(false)
            setPreviewFile(null)
            setPreviewAnalyze(null)
          }}
          onSuccess={(res) => {
            queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
            queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
            if (res.table_id) {
              navigate(`/w/${wid}/tables/${res.table_id}`)
            }
          }}
        />
      </Suspense>
    </div>
  )
}

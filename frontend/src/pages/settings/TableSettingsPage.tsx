/** 数据表设置页 — 四个 Tab：基本信息 / 字段 / 视图 / 权限.
 *
 * 由 TableSettingsModal 页面化而来（P3）：挂载于 /w/:wid/tables/:tid/settings，
 * 当前 Tab 由 URL search param ?tab= 驱动，便于二级导航与刷新保持状态。
 *
 * 聚合 FieldManager（字段）、PermissionEditor（权限）、CreateEditViewForm（视图创建/编辑）。
 */

import { Suspense, lazy, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Modal, Tabs, Form, Input, Button, Tag, Popconfirm, App as AntApp, Space, Empty, Tooltip, Select,
} from 'antd'
import {
  InfoCircleOutlined, UnorderedListOutlined, AppstoreOutlined, SafetyOutlined,
  SaveOutlined, EditOutlined, PlusOutlined, DeleteOutlined, StarOutlined,
  ColumnHeightOutlined, CalendarOutlined, LineChartOutlined, PartitionOutlined,
  ApartmentOutlined,
  HolderOutlined, TableOutlined, BarChartOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useResponsive } from '@/hooks/useResponsive'
import {
  DndContext, type DragEndEvent, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { tableApi, permissionApi, viewApi } from '@/api'
import type { TableDetail, TableUpdate, ViewCreate, View } from '@/api'
import PermissionEditor, { buildHiddenSet } from '@/pages/grid/permissions/PermissionEditor'
// 静态引入：gridViewModals 同为静态引入，混用 lazy 会让动态分包失效并产生构建告警
import CreateEditViewForm from '@/pages/grid/view-config/CreateEditViewForm'

const FieldManager = lazy(() => import('@/pages/fields/FieldManager'))

/** 视图类型 → 中文标签 + 图标（与 GridPage MODE_BUTTONS 保持一致） */
const VIEW_MODE_META: Record<string, { label: string; icon: ReactNode }> = {
  grid: { label: '表格 (Grid)', icon: <ColumnHeightOutlined /> },
  tree: { label: '树 (Tree)', icon: <ApartmentOutlined /> },
  kanban: { label: '看板 (Kanban)', icon: <AppstoreOutlined /> },
  calendar: { label: '日历 (Calendar)', icon: <CalendarOutlined /> },
  gantt: { label: '甘特图 (Gantt)', icon: <LineChartOutlined /> },
  wbs: { label: '工作分解 (WBS)', icon: <PartitionOutlined /> },
  matrix: { label: '矩阵 (Matrix)', icon: <TableOutlined /> },
  chart: { label: '图表 (Chart)', icon: <BarChartOutlined /> },
}

export type TableSettingsTab = 'basic' | 'fields' | 'views' | 'permissions'

function hasAction(actions: string[] | undefined, action: string): boolean {
  return Array.isArray(actions) && actions.includes(action)
}

/** 可拖拽排序的视图行.
 *
 * 拖拽手柄（HolderOutlined）独立挂载 listeners，避免整行拖拽与行内编辑/删除按钮的事件冲突.
 */
function SortableViewRow({
  view, canEdit, onEdit, onDelete, onSetDefault, settingDefault,
}: {
  view: View
  canEdit: boolean
  onEdit: () => void
  onDelete: () => void
  onSetDefault: () => void
  settingDefault: boolean
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: String(view.id),
  })
  const meta = VIEW_MODE_META[view.view_type]
  // 缺省视为 table 档：老接口响应 / 测试 mock 不带 visibility 时保持原有入口可见
  const isTableTierView = (view.visibility ?? 'table') === 'table'
  return (
    <div
      ref={setNodeRef}
      className="ts-view-row"
      data-testid={`ts-view-row-${view.id}`}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
      }}
    >
      <span
        className="ts-view-drag"
        aria-label={`拖拽排序 ${view.name}`}
        title={canEdit ? '拖拽调整顺序' : undefined}
        style={{ cursor: canEdit ? 'grab' : 'default' }}
        {...attributes}
        {...listeners}
      >
        <HolderOutlined />
      </span>
      <span className="ts-view-icon">{meta?.icon ?? <AppstoreOutlined />}</span>
      <strong className="ts-view-name">{view.name}</strong>
      <Tag style={{ marginInlineEnd: 0 }}>{meta?.label ?? view.view_type}</Tag>
      {view.is_default && <Tag color="blue" style={{ marginInlineEnd: 0 }}>默认</Tag>}
      <span className="ts-view-actions">
        {/* is_default 是**表级**标记：只有表内可见（table 档）视图才代表全表落地页。
            私有/指定成员档视图持有它会让其他成员进表看到空白，后端会 400，故此处不给入口。 */}
        {canEdit && !view.is_default && (
          <Tooltip title={isTableTierView ? '设为默认视图' : '仅「表内可见」的视图可设为默认'}>
            <Button
              size="small"
              type="text"
              icon={<StarOutlined />}
              aria-label={`设为默认视图 ${view.name}`}
              loading={settingDefault}
              disabled={!isTableTierView}
              onClick={onSetDefault}
            />
          </Tooltip>
        )}
        <Tooltip title="编辑视图">
          <Button size="small" type="text" icon={<EditOutlined />} disabled={!canEdit} onClick={onEdit} />
        </Tooltip>
        {/* 不能在 Popconfirm 内嵌 Tooltip：Tooltip 浮层会覆盖确认弹层导致无法确认 */}
        <Popconfirm
          title={`删除视图 "${view.name}" ？`}
          description="视图规则一并删除，不影响表数据"
          okText="删除"
          okType="danger"
          cancelText="取消"
          onConfirm={onDelete}
          disabled={!canEdit}
        >
          <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={!canEdit} aria-label={`删除视图 ${view.name}`} />
        </Popconfirm>
      </span>
    </div>
  )
}

/** 数据表设置页主体（路由页面，无 Modal 外壳；wid/tid 由路由参数提供） */
export default function TableSettingsPage() {
  const { wid = '', tid = '' } = useParams<{ wid: string; tid: string }>()
  const { message } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  /** 当前 Tab：以 URL ?tab= 为唯一真相源（缺省 basic） */
  const activeTab = (searchParams.get('tab') as TableSettingsTab | null) ?? 'basic'
  const [form] = Form.useForm<TableUpdate>()
  const [viewEditorOpen, setViewEditorOpen] = useState(false)
  const [viewEditorInitial, setViewEditorInitial] = useState<{
    vid?: number | string
    name?: string
    viewType?: string
    options?: Record<string, unknown>
  }>({})
  /** 权限 Tab 隐藏字段受控 state（保存时直接读取，不再依赖 DOM 采集） */
  const [hiddenNames, setHiddenNames] = useState<string[]>([])
  /** 数据治理（MANAGE_DATA）最低角色阈值；空串 = 使用默认 ADMIN */
  const [manageDataRole, setManageDataRole] = useState<string>('')

  // 基本信息表单值监听（脏检查用）
  const nameValue = Form.useWatch('name', form)
  const descriptionValue = Form.useWatch('description', form)

  // 表详情（含统计 + current_user_actions + 视图摘要）
  const { data: table, isLoading } = useQuery<TableDetail>({
    queryKey: ['table-settings', wid, tid],
    queryFn: () => tableApi.get(wid, tid),
  })

  // 视图列表（完整列表用于 Tab3 内联展示/编辑）
  const { data: views = [] } = useQuery({
    queryKey: ['table-views', wid, tid],
    queryFn: () => viewApi.list(wid, tid),
  })

  // 权限数据（切到 permissions Tab 时 refetch）
  const { data: permData, refetch: refetchPerm } = useQuery({
    queryKey: ['table-perm', wid, tid],
    queryFn: () => permissionApi.get(wid, tid),
    enabled: false,
  })

  // 基本信息更新
  const updateTable = useMutation({
    mutationFn: (data: TableUpdate) => tableApi.update(wid, tid, data),
    onSuccess: () => {
      message.success('已保存')
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table', `${wid}/${tid}`] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存失败'),
  })

  const removeTable = useMutation({
    mutationFn: () => tableApi.remove(wid, tid),
    onSuccess: () => {
      message.success('表已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
      // 删除后退出到工作区表列表，避免停留在已删除表的路由上
      navigate(`/w/${wid}/tables`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除表失败'),
  })

  const savePerm = useMutation({
    mutationFn: (data: Parameters<typeof permissionApi.patch>[2]) => permissionApi.patch(wid, tid, data),
    onSuccess: () => {
      message.success('权限已更新')
      queryClient.invalidateQueries({ queryKey: ['table-perm', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存权限失败'),
  })

  const createView = useMutation({
    mutationFn: (data: ViewCreate) => viewApi.create(wid, tid, data),
    onSuccess: () => {
      message.success('视图已创建')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建视图失败'),
  })
  const updateView = useMutation({
    mutationFn: (args: { vid: number | string; data: Partial<ViewCreate> }) =>
      viewApi.update(wid, tid, args.vid, args.data),
    onSuccess: () => {
      message.success('视图已更新')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新视图失败'),
  })
  const removeView = useMutation({
    mutationFn: (vid: number | string) => viewApi.remove(wid, tid, vid),
    onSuccess: () => {
      message.success('视图已删除')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除视图失败'),
  })

  // 设为默认视图：后端会清除同表其它视图的 default 标记
  const setDefaultView = useMutation({
    mutationFn: (vid: number | string) => viewApi.update(wid, tid, vid, { is_default: true }),
    onSuccess: () => {
      message.success('已设为默认视图')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '设置默认视图失败'),
  })

  // ── 视图顺序拖拽 ──
  const viewDragSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  const reorderViews = useMutation({
    mutationFn: (ids: Array<number | string>) => viewApi.reorder(wid, tid, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '视图排序失败'),
  })
  const handleViewDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    // views 已按后端 order 排序
    const oldIndex = views.findIndex(v => String(v.id) === String(active.id))
    const newIndex = views.findIndex(v => String(v.id) === String(over.id))
    if (oldIndex < 0 || newIndex < 0) return
    reorderViews.mutate(arrayMove(views, oldIndex, newIndex).map(v => v.id))
  }

  const handleTabChange = (key: string) => {
    // Tab 变化同步到 URL，刷新/二级导航保持状态
    setSearchParams(key === 'basic' ? {} : { tab: key }, { replace: true })
  }

  // 权限数据加载：进入 permissions Tab 时触发（useEffect 覆盖 ?tab=permissions 直达场景）
  useEffect(() => {
    if (activeTab === 'permissions') refetchPerm()
  }, [activeTab, refetchPerm])

  // 权限数据到达后展平初始化隐藏字段受控 state
  useEffect(() => {
    if (permData) setHiddenNames(Array.from(buildHiddenSet(permData.hidden_fields)))
  }, [permData])

  // 权限数据到达后初始化数据治理角色阈值
  useEffect(() => {
    if (permData) setManageDataRole(permData.manage_data_role ?? '')
  }, [permData])

  // 表切换时，初始化基本信息表单
  useEffect(() => {
    if (table) {
      form.setFieldsValue({ name: table.name, description: table.description })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table?.id])

  const actions = table?.current_user_actions ?? []
  const canEditSchema = hasAction(actions, 'edit_schema')
  const canEditViews = hasAction(actions, 'edit_views')
  const canEditRecords = hasAction(actions, 'edit_records')
  const canEditBasic = canEditSchema
  const canDeleteTable = !table?.trashed && canEditSchema

  // 基本信息脏检查：与当前表数据比对，无变化时禁用保存按钮
  const basicDirty = !!table && (
    (nameValue ?? '') !== (table.name ?? '') ||
    (descriptionValue ?? '') !== (table.description ?? '')
  )

  const tabs = (
    <Tabs
      // 移动端竖排页签会挤占本就有限的内容宽度，改为顶部横排（可横向滚动）
      tabPosition={isMobile ? 'top' : 'left'}
      className="table-settings-tabs"
      activeKey={activeTab}
      onChange={handleTabChange}
      items={[
        // ────────────── Tab 1: 基本信息 ──────────────
        {
          key: 'basic',
          label: <span><InfoCircleOutlined /> 基本信息</span>,
          children: table ? (
            <div style={{ paddingTop: 4 }}>
              {/* 统计条 — 替代原 bordered Descriptions，更紧凑 */}
              <div className="ts-stats">
                <div className="ts-stat">
                  <span className="ts-stat-num">{table.field_count ?? table.fields.length}</span>
                  <span className="ts-stat-label">字段</span>
                </div>
                <div className="ts-stat">
                  <span className="ts-stat-num">{table.record_count ?? 0}</span>
                  <span className="ts-stat-label">记录</span>
                </div>
                <div className="ts-stat">
                  <span className="ts-stat-num">{table.view_count ?? (table.views?.length ?? 0)}</span>
                  <span className="ts-stat-label">视图</span>
                </div>
                <div className="ts-stat">
                  <span className="ts-stat-num ts-stat-num-sm">
                    {table.created_at ? new Date(table.created_at).toLocaleDateString() : '—'}
                  </span>
                  <span className="ts-stat-label">创建日期</span>
                </div>
              </div>
              <div className="ts-meta">表 ID {table.id} · 工作区 {table.workspace_id}</div>

              <Form
                key={`basic-${table?.id ?? 'loading'}`}
                form={form}
                layout="vertical"
                initialValues={{ name: table?.name ?? '', description: table?.description ?? '' }}
                onFinish={(v) => updateTable.mutate(v)}
              >
                <Form.Item
                  name="name"
                  label="表名"
                  style={{ marginBottom: 12 }}
                  rules={[{ required: true, message: '请输入表名' }, { max: 64 }]}
                >
                  <Input maxLength={64} showCount disabled={!canEditBasic} />
                </Form.Item>
                <Form.Item name="description" label="描述（可选）" style={{ marginBottom: 12 }}>
                  <Input.TextArea rows={3} maxLength={500} showCount disabled={!canEditBasic} />
                </Form.Item>

                <Space>
                  <Button
                    type="primary"
                    icon={<SaveOutlined />}
                    htmlType="submit"
                    loading={updateTable.isPending}
                    disabled={!canEditBasic || !basicDirty}
                  >
                    保存
                  </Button>
                  <Popconfirm
                    title={`删除表 "${table.name}" ？`}
                    description="表内所有记录和字段将被永久移除。此操作不可恢复。"
                    okText="删除"
                    okType="danger"
                    cancelText="取消"
                    onConfirm={() => removeTable.mutate()}
                    disabled={!canDeleteTable}
                  >
                    <Button danger icon={<DeleteOutlined />} disabled={!canDeleteTable}>
                      删除表
                    </Button>
                  </Popconfirm>
                  {!canDeleteTable && table && (
                    <Tag color="warning" style={{ marginLeft: 8 }}>
                      需要「编辑表结构」权限才能删除此表
                    </Tag>
                  )}
                </Space>
              </Form>
            </div>
          ) : <Empty description={isLoading ? '加载中...' : '未找到该表'} />,
        },

        // ────────────── Tab 2: 字段 ──────────────
        {
          key: 'fields',
          label: <span><UnorderedListOutlined /> 字段</span>,
          children: (
            <Suspense fallback={<div style={{ padding: 48, textAlign: 'center' }}>加载字段管理器...</div>}>
              <FieldManager
                embedded
                open={true}
                wid={wid}
                tid={tid}
                fields={table?.fields ?? []}
                onClose={() => { }}
                onChanged={() => {
                  queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
                  queryClient.invalidateQueries({ queryKey: ['table', `${wid}/${tid}`] })
                  queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
                }}
              />
            </Suspense>
          ),
        },

        // ────────────── Tab 3: 视图 ──────────────
        {
          key: 'views',
          label: <span><AppstoreOutlined /> 视图</span>,
          children: (
            <div style={{ paddingTop: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <span style={{ color: 'var(--cn-text-secondary)', fontSize: 13 }}>
                  共 {views.length} 个视图
                  {views.length > 1 && <span style={{ marginLeft: 8, fontSize: 12 }}>· 拖拽左侧手柄调整顺序</span>}
                </span>
                <Button
                  type="primary"
                  size="small"
                  icon={<PlusOutlined />}
                  disabled={!canEditViews}
                  onClick={() => {
                    setViewEditorInitial({})
                    setViewEditorOpen(true)
                  }}
                >
                  新建视图
                </Button>
              </div>

              {views.length === 0 && (
                <Empty description="暂无视图，点击右上角「新建视图」创建" style={{ padding: 32 }} />
              )}

              <DndContext
                sensors={viewDragSensors}
                collisionDetection={closestCenter}
                onDragEnd={handleViewDragEnd}
              >
                <SortableContext
                  items={views.map((v: View) => String(v.id))}
                  strategy={verticalListSortingStrategy}
                >
                  {views.map((v: View) => (
                    <SortableViewRow
                      key={String(v.id)}
                      view={v}
                      canEdit={canEditViews}
                      settingDefault={setDefaultView.isPending && setDefaultView.variables === v.id}
                      onSetDefault={() => setDefaultView.mutate(v.id)}
                      onEdit={() => {
                        setViewEditorInitial({
                          vid: v.id,
                          name: v.name,
                          viewType: v.view_type,
                          options: v.view_options ?? undefined,
                        })
                        setViewEditorOpen(true)
                      }}
                      onDelete={() => removeView.mutate(v.id)}
                    />
                  ))}
                </SortableContext>
              </DndContext>
            </div>
          ),
        },

        // ────────────── Tab 4: 权限 ──────────────
        {
          key: 'permissions',
          label: <span><SafetyOutlined /> 权限</span>,
          children: table ? (
            <div style={{ paddingTop: 4 }}>
              <div style={{ marginBottom: 10 }}>
                <span style={{ fontSize: 13, color: 'var(--cn-text-primary)', marginRight: 8 }}>您当前在本表的权限：</span>
                <Space size={[4, 4]} wrap>
                  {canEditRecords && <Tag color="blue">编辑记录</Tag>}
                  {canEditViews && <Tag color="purple">编辑视图</Tag>}
                  {canEditSchema && <Tag color="gold">编辑结构</Tag>}
                  {hasAction(actions, 'manage_data') && <Tag color="geekblue">数据治理</Tag>}
                  {!canEditRecords && !canEditViews && !canEditSchema && <Tag color="default">仅查看</Tag>}
                </Space>
              </div>

              {/* 数据治理角色阈值：最低需要什么工作区角色才能执行合并/清洗 */}
              <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13 }}>数据治理权限（合并/清洗）：</span>
                <Select
                  size="small"
                  style={{ width: 160 }}
                  value={manageDataRole}
                  onChange={setManageDataRole}
                  disabled={!canEditSchema}
                  options={[
                    { value: '', label: '默认（编辑者）' },
                    { value: 'viewer', label: 'viewer（可查看）' },
                    { value: 'editor', label: 'editor（可编辑）' },
                    { value: 'owner', label: 'owner（拥有者）' },
                  ]}
                />
              </div>

              <PermissionEditor
                fields={table.fields ?? []}
                wid={wid}
                tid={tid}
                owner={table.owner ?? null}
                hiddenNames={hiddenNames}
                onHiddenNamesChange={setHiddenNames}
              />

              <div style={{ marginTop: 16, textAlign: 'right' }}>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={savePerm.isPending}
                  disabled={!canEditSchema}
                  onClick={() => {
                    // 隐藏字段受控 state 直读 + 数据治理角色阈值；不再携带 row_filters（PATCH exclude_unset 语义下避免误清空）
                    // 桶键用 viewer（对查看者隐藏；后端按工作区角色取桶，admin 键在三级角色下永不命中）
                    savePerm.mutate({ hidden_fields: { viewer: hiddenNames }, manage_data_role: manageDataRole })
                  }}
                >
                  保存权限
                </Button>
              </div>
            </div>
          ) : <Empty description="加载中..." />,
        },
      ]}
    />
  )

  // 视图表单弹层 — 创建 / 编辑共用
  const viewEditor = viewEditorOpen && (
    <Modal
      title={viewEditorInitial.vid ? '编辑视图' : '新建视图'}
      open={true}
      onCancel={() => setViewEditorOpen(false)}
      footer={null}
      width={720}
      className="cevf-modal"
      destroyOnHidden
    >
      <CreateEditViewForm
        fields={table?.fields ?? []}
        initialName={viewEditorInitial.name}
        initialType={viewEditorInitial.viewType}
        initialOptions={viewEditorInitial.options}
        submitLabel={viewEditorInitial.vid ? '保存' : '创建'}
        onSubmit={(name, vt, opts) => {
          if (viewEditorInitial.vid != null) {
            updateView.mutate({
              vid: viewEditorInitial.vid,
              data: { name, view_type: vt, ...(opts && Object.keys(opts).length ? { view_options: opts } : {}) },
            })
          } else {
            createView.mutate({
              name, view_type: vt,
              ...(opts && Object.keys(opts).length ? { view_options: opts } : {}),
            })
          }
          setViewEditorOpen(false)
        }}
      />
    </Modal>
  )

  return (
    <div style={{ padding: '16px 24px', height: '100%', overflow: 'auto' }}>
      {tabs}
      {viewEditor}
    </div>
  )
}

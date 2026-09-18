/** Grid 主应用 — 集成视图 Tab / 四种视图 / inline 编辑 / 导入导出 / 行复制.
 *
 * 组件拆分说明（重构自 2400 行单体）:
 *   components/
 *     ├─ KanbanView.tsx         — 看板视图
 *     ├─ CalendarView.tsx       — 日历视图
 *     ├─ GalleryView.tsx        — 画廊视图
 *     ├─ GridCell.tsx           — inline 编辑单元格
 *     ├─ RowDetailDrawer.tsx     — 行详情抽屉
 *     ├─ ViewConfigDialog.tsx    — 筛选/排序/视图设置对话框
 *     ├─ CreateEditViewForm.tsx  — 创建/编辑视图表单（合并版）
 *     ├─ ColumnFilterDropdown.tsx — 列级筛选下拉
 *     ├─ PermissionEditor.tsx    — 权限编辑器
 *     ├─ MoveTableForm.tsx       — 移动表表单
 *     ├─ TableSettingsDialog.tsx — 全局显示设置
 *     ├─ buildColumns.tsx        — Grid 列构建函数
 *     ├─ fieldOps.ts             — 字段操作符常量（统一真相源）
 *     └─ fieldValueFormat.ts     — 字段值格式化工具
 */

import { Suspense, lazy, useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Table, Button, Space, Tag, Modal, Typography, message, Tooltip, Dropdown, Empty, Input, Segmented, Switch, Upload, Popconfirm } from 'antd'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, ColumnHeightOutlined,
  FilterOutlined, MoreOutlined, ArrowLeftOutlined, EyeOutlined, SettingOutlined,
  AppstoreOutlined, CopyOutlined, ImportOutlined, UploadOutlined, CloseOutlined,
  CalendarOutlined, ShareAltOutlined, SwapOutlined, LineChartOutlined,
  SearchOutlined, EditOutlined, MenuOutlined, PartitionOutlined, HolderOutlined,
} from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTable, useTableViews, useActiveViewPreference, useTableRecords, useUpdateRowOptimistic, useDeleteRowsOptimistic } from '@/api/hooks'
import {
  DndContext, DragEndEvent, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { tableApi, recordApi, viewApi, userApi, auditApi, commentApi } from '@/api'
import type { RowResponse, View, ViewCreate, RowValues, Field, ID } from '@/api'
import KanbanView from './components/KanbanView'
import CalendarView from './components/CalendarView'
import GalleryView from './components/GalleryView'
import GanttView from './components/GanttView'
import WbsView from './components/WbsView'
import RowDetailDrawer from './components/RowDetailDrawer'
import ViewConfigDialog, { type FilterRule, type SortRule } from './components/ViewConfigDialog'
import CreateEditViewForm from './components/CreateEditViewForm'
import MoveTableForm from './components/MoveTableForm'
import TableSettingsDialog from './components/TableSettingsDialog'
import TableSettingsModal from '@/pages/modals/TableSettingsModal'
import { buildColumns, type RowInlineOps, type InlineEditCellProps } from './components/buildColumns'
import { finalizeCellValue, isBlankCellValue, isEditableInlineField, normalizeCellValueForEdit } from './components/GridCell'
import { useTableSettingsStore, useGridViewStore } from '@/store'
import { densityToSize } from '@/theme/tableSettings'

// Modal 组件 lazy import：点击打开时才加载
const FieldManager = lazy(() => import('@/pages/modals/FieldManager'))
const ImportExportDialog = lazy(() => import('@/pages/modals/ImportExportDialog'))

function ModalFallback() {
  return null
}

const { Text } = Typography
type ViewMode = 'grid' | 'kanban' | 'gallery' | 'calendar' | 'gantt' | 'wbs'
const VALID_MODES: readonly ViewMode[] = ['grid', 'kanban', 'gallery', 'calendar', 'gantt', 'wbs']
const MODE_STORAGE_KEY = 'cndb_current_mode'

/** 右侧模式按钮配置 —— 顺序即显示顺序；仅当数据表存在对应 view_type 的视图时才渲染. */
interface ModeBtn {
  mode: ViewMode
  tooltip: string
  icon: React.ReactNode
}
const MODE_BUTTONS: readonly ModeBtn[] = [
  { mode: 'grid', tooltip: '表格', icon: <ColumnHeightOutlined /> },
  { mode: 'kanban', tooltip: '看板', icon: <AppstoreOutlined /> },
  { mode: 'gallery', tooltip: '画廊', icon: <EyeOutlined /> },
  { mode: 'calendar', tooltip: '日历', icon: <CalendarOutlined /> },
  { mode: 'gantt', tooltip: '甘特图', icon: <LineChartOutlined /> },
  { mode: 'wbs', tooltip: '工作分解', icon: <PartitionOutlined /> },
]

/** 安全读取 localStorage（SSR / 隐私模式下可能抛异常）. */
function _readModeFromStorage(): ViewMode | null {
  try {
    const m = localStorage.getItem(MODE_STORAGE_KEY)
    if (m && (VALID_MODES as readonly string[]).includes(m)) return m as ViewMode
  } catch { /* localStorage 不可用时忽略 */ }
  return null
}

/** 可拖拽视图 Tab 标签 —— 供 Segmented.options.label 使用，配合 DndContext + SortableContext. */
function DndViewTab({ view, active, onClick }: { view: View; active: boolean; onClick: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: String(view.id),
  })
  return (
    <span
      ref={setNodeRef}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
        cursor: active ? 'pointer' : 'grab',
        userSelect: 'none',
      }}
      data-testid={`view-tab-${view.id}`}
      {...attributes}
      {...listeners}
      onClick={(e) => { e.stopPropagation(); onClick() }}
    >
      <HolderOutlined style={{ fontSize: 10, color: '#bfbfbf' }} />
      <span>{view.name}</span>
      {view.default && <Tag color="blue" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>默认</Tag>}
    </span>
  )
}

export default function GridPage() {
  const { wid, tid } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const density = useTableSettingsStore(s => s.density)
  const defaultPageSize = useTableSettingsStore(s => s.defaultPageSize)
  const bordered = useTableSettingsStore(s => s.bordered)
  const showHeader = useTableSettingsStore(s => s.showHeader)
  const striped = useTableSettingsStore(s => s.striped)
  const settings = { density, defaultPageSize, bordered, showHeader, striped }

  // —— 视图状态从 GridViewStore 订阅 ——
  const mode = useGridViewStore(s => s.mode)
  const setMode = useGridViewStore(s => s.setMode)
  const activeViewId = useGridViewStore(s => s.activeViewId)
  const setActiveViewId = useGridViewStore(s => s.setActiveViewId)
  const viewFilters = useGridViewStore(s => s.viewFilters)
  const setViewFilters = useGridViewStore(s => s.setViewFilters)
  const updateViewFilters = useGridViewStore(s => s.updateViewFilters)
  const viewSortings = useGridViewStore(s => s.viewSortings)
  const setViewSortings = useGridViewStore(s => s.setViewSortings)
  const updateViewSortings = useGridViewStore(s => s.updateViewSortings)
  const viewFilterLogic = useGridViewStore(s => s.viewFilterLogic)
  const setViewFilterLogic = useGridViewStore(s => s.setViewFilterLogic)
  const viewOptionsDraft = useGridViewStore(s => s.viewOptionsDraft)
  const setViewOptionsDraft = useGridViewStore(s => s.setViewOptionsDraft)
  const searchQuery = useGridViewStore(s => s.searchQuery)
  const setSearchQuery = useGridViewStore(s => s.setSearchQuery)
  const offset = useGridViewStore(s => s.offset)
  const setOffset = useGridViewStore(s => s.setOffset)
  const limit = useGridViewStore(s => s.limit)
  const setLimit = useGridViewStore(s => s.setLimit)
  const patchView = useGridViewStore(s => s.patch)
  const resetView = useGridViewStore(s => s.reset)

  // wid/tid 变化时重置 store + 初始化 mode
  useEffect(() => {
    resetView()
    // 行内编辑状态重置
    setEditingRowId(null)
    setNewRowActive(false)
    setRowDrafts({})
    // 恢复当前表的 mode 偏好（URL > localStorage > 默认 grid）
    const spMode = searchParams.get('mode') as ViewMode | null
    if (spMode && (VALID_MODES as readonly string[]).includes(spMode)) {
      setMode(spMode)
    } else {
      const lsMode = _readModeFromStorage()
      if (lsMode) setMode(lsMode)
    }
    // 搜索词恢复
    const q = searchParams.get('q')
    if (q) setSearchQuery(q)
    setLimit(settings.defaultPageSize)
  }, [wid, tid]) // eslint-disable-line react-hooks/exhaustive-deps

  const [settingsOpen, setSettingsOpen] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRow, setDetailRow] = useState<RowResponse | null>(null)
  const [fieldMgrOpen, setFieldMgrOpen] = useState(false)
  const [importExportOpen, setImportExportOpen] = useState(false)
  const [viewConfigOpen, setViewConfigOpen] = useState(false)
  const [createViewOpen, setCreateViewOpen] = useState(false)
  const [editViewOpen, setEditViewOpen] = useState(false)
  const [importViewsOpen, setImportViewsOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importFileContent, setImportFileContent] = useState('')
  const [moveOpen, setMoveOpen] = useState(false)
  const [tableSettingsOpen, setTableSettingsOpen] = useState(false)
  const [tableSettingsTab, setTableSettingsTab] = useState<'basic' | 'fields' | 'views' | 'permissions'>('basic')
  const tableKey = `${wid}/${tid}`

  // ── 行内编辑（新增行 / 整行编辑）状态 ──
  const NEW_ROW_KEY = '__new__'
  /** 整行编辑模式下的行 id（null 表示无行处于整行编辑） */
  const [editingRowId, setEditingRowId] = useState<ID | null>(null)
  /** 底部空白新增行是否激活 */
  const [newRowActive, setNewRowActive] = useState(false)
  /** 各编辑态行的草稿值，key 为 `row-${id}`；新增行固定用 NEW_ROW_KEY */
  const [rowDrafts, setRowDrafts] = useState<Record<string, RowValues>>({})

  const rowKeyOf = (recordId: ID) => `row-${recordId}`
  const isNewRow = (recordId: ID) => String(recordId) === NEW_ROW_KEY
  const inlineDataKey = (recordId: ID) => (isNewRow(recordId) ? NEW_ROW_KEY : rowKeyOf(recordId))

  /** 切换视图 loadView 期间临时阻止自动保存（刚加载完的 state 不应立即回写）. */
  const skipSaveRef = useRef(false)

  /** 打开行详情抽屉并预取 audit/comments/references —— queryKey 与 RowDetailDrawer 的自定义 hooks 完全一致. */
  const openDetailWithPrefetch = useCallback((r: RowResponse) => {
    setDetailRow(r)
    setDetailOpen(true)
    if (wid && tid && r.id != null) {
      const rowId = r.id
      void queryClient.prefetchQuery({
        queryKey: ['row-audit', wid, tid, rowId],
        queryFn: () => auditApi.list(wid, tid, undefined, 20, rowId),
        staleTime: 60_000,
      })
      void queryClient.prefetchQuery({
        queryKey: ['row-comments', wid, tid, rowId],
        queryFn: () => commentApi.list(wid, tid, rowId),
        staleTime: 60_000,
      })
      void queryClient.prefetchQuery({
        queryKey: ['row-references', wid, tid, rowId],
        queryFn: () => tableApi.references(wid, tid, rowId),
        staleTime: 60_000,
      })
    }
  }, [wid, tid, queryClient])

  const { data: table, isLoading } = useTable(wid!, tid!)
  const { data: views = [] } = useTableViews(wid!, tid!)
  /** 用户偏好：当前表的激活视图 ID（per-user per-table 持久化） */
  const { data: activeViewPreference } = useActiveViewPreference(Number(tid))
  /** 保存激活视图偏好（debounce 在 loadView 里手动控制） */
  const saveActiveViewPref = useMutation({
    mutationFn: (vid: number | null) => userApi.setTableActiveView(Number(tid!), vid),
  })
  /** 把后端存储的 filters（dict 或 list）归一化成 list 形式 */
  function normalizeFilters(raw: unknown): FilterRule[] {
    if (!raw) return []
    if (Array.isArray(raw)) {
      return raw
        .filter((r): r is Record<string, unknown> => typeof r === 'object' && r !== null)
        .map(r => ({
          field_name: String(r.field_name ?? ''),
          op: String(r.op ?? '='),
          ...(r.value !== undefined && r.value !== null ? { value: r.value } : {}),
        }))
    }
    if (typeof raw === 'object') {
      const result: FilterRule[] = []
      for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
        if (k === '$query') continue  // 特殊 key 跳过
        if (typeof v === 'object' && v !== null && 'op' in v) {
          const vv = v as { op: string; value?: unknown }
          result.push({ field_name: k, op: vv.op, ...(vv.value !== undefined ? { value: vv.value } : {}) })
        } else {
          result.push({ field_name: k, op: '=', value: v })
        }
      }
      return result
    }
    return []
  }

  // 加载 active view 的 filters + view_options
  const loadView = (v: View | null, updateUrl = true, persistMode = true) => {
    skipSaveRef.current = true // 切换视图期间阻止自动保存
    if (v) {
      const KANBAN_MODES = new Set<string>(['kanban', 'gallery', 'calendar', 'gantt', 'wbs'])
      const vt = v.view_type ?? ''
      const newMode: ViewMode = KANBAN_MODES.has(vt) ? (vt as ViewMode) : 'grid'

      patchView({
        activeViewId: v.id,
        viewFilters: normalizeFilters(v.filters),
        viewSortings: Array.isArray(v.sortings) ? v.sortings : [],
        viewFilterLogic: (v.filter_type ?? 'AND') as 'AND' | 'OR',
        viewOptionsDraft: v.view_options ?? null,
        mode: newMode,
        offset: 0,
      })

      // 全局模式持久化（localStorage + URL）—— 跨表切换时自动找回相同视图类型
      // persistMode=false 时（如初始化 fallback 到 default 视图）跳过，不覆盖用户之前的偏好
      if (persistMode) {
        try { localStorage.setItem(MODE_STORAGE_KEY, newMode) } catch { /* localStorage 不可用时忽略 */ }
      }
      if (updateUrl) {
        const params = new URLSearchParams(searchParams)
        params.set('view', String(v.id))
        params.set('mode', newMode)
        setSearchParams(params, { replace: true })
        // 用户主动切换视图 —— 持久化偏好到后端
        saveActiveViewPref.mutate(Number(v.id))
      }
    } else {
      patchView({
        activeViewId: null,
        viewFilters: [],
        viewSortings: [],
        viewFilterLogic: 'AND',
        viewOptionsDraft: null,
        mode: 'grid',
        offset: 0,
      })

      if (persistMode) {
        try { localStorage.setItem(MODE_STORAGE_KEY, 'grid') } catch { /* localStorage 不可用时忽略 */ }
      }
      if (updateUrl) {
        const params = new URLSearchParams(searchParams)
        params.delete('view')
        params.delete('mode')
        setSearchParams(params, { replace: true })
      }
    }
    // 等 React 批量渲染完 + useEffect 检查过一遍（此时 skipSaveRef=true 会被正确跳过），再放开自动保存
    setTimeout(() => { skipSaveRef.current = false }, 50)
  }

  // 当前激活的视图对象（含 view_options）
  const activeView = activeViewId != null ? views.find(v => String(v.id) === String(activeViewId)) : null

  // 视图初始化 / 重新匹配：URL ?view= 深链 > URL ?mode= 匹配 > localStorage mode 匹配 > 用户偏好 active_view_id > is_default > 第一个
  // 每次 wid/tid/searchParams/views/activeViewPreference 变化时都重新评估，
  // 但只有当目标视图和当前 activeViewId 不同时才实际切换，避免无限循环.
  useEffect(() => {
    if (!views.length) return

    // ── 计算最匹配的目标视图 ──
    let target: View | null = null

    // 1. URL 深链优先（精确 view id）
    const vidParam = searchParams.get('view')
    if (vidParam) {
      target = views.find(v => String(v.id) === vidParam) || null
    }
    // 2. URL mode 匹配（刷新 / 从其它表带 ?mode= 导航过来时保留展示模式）
    if (!target) {
      const spMode = searchParams.get('mode') as ViewMode | null
      if (spMode && VALID_MODES.includes(spMode)) {
        target = views.find(v => v.view_type === spMode) || null
      }
    }
    // 3. localStorage mode 匹配（侧边栏点表导航丢失 URL 参数时的兜底）
    if (!target) {
      const lsMode = _readModeFromStorage()
      if (lsMode) {
        target = views.find(v => v.view_type === lsMode) || null
      }
    }
    // 4. 用户偏好的激活视图（后端存储 per-table）—— 异步加载完成后也能触发重新评估
    if (!target) {
      const prefVid = activeViewPreference?.active_view_id
      if (prefVid != null) {
        target = views.find(v => Number(v.id) === prefVid) || null
      }
    }
    // 5. 最后：default 或第一个
    if (!target) {
      target = views.find(v => v.default) || views[0] || null
    }

    // ── 只在目标和当前不同时才切换（初始化都不持久化 mode，避免覆盖用户偏好） ──
    if (target) {
      if (activeViewId !== String(target.id)) {
        loadView(target, false, false)
      }
    } else if (activeViewId !== null) {
      loadView(null, false, false)
    }
  }, [views, searchParams, wid, tid, activeViewPreference])  // eslint-disable-line react-hooks/exhaustive-deps

  // searchQuery URL 深链：?q=关键词
  useEffect(() => {
    const expected = searchQuery.trim()
    const current = searchParams.get('q') || ''
    if (expected === current) return
    const params = new URLSearchParams(searchParams)
    if (expected) params.set('q', expected)
    else params.delete('q')
    setSearchParams(params, { replace: true })
  }, [searchQuery])  // eslint-disable-line react-hooks/exhaustive-deps

  // 当前生效的筛选条件（视图筛选 + 全局关键词）
  const effectiveFilters = useMemo(() => {
    const list: Array<Record<string, unknown>> = viewFilters as unknown as Array<Record<string, unknown>>
    if (searchQuery.trim()) list.push({ field_name: '__query__', op: 'contains', value: searchQuery.trim() })
    return list.length ? list : undefined
  }, [viewFilters, searchQuery])

  // 当前生效的排序条件
  const sortsParam = useMemo(() => {
    return viewSortings.length ? (viewSortings as unknown as Array<Record<string, unknown>>) : undefined
  }, [viewSortings])

  // 非 grid 视图需要全量数据（日历/看板/画廊要跨月/跨列聚合），绕过分页
  const VIEW_FETCH_ALL_LIMIT = 5000
  const effectiveLimit = mode === 'grid' ? limit : VIEW_FETCH_ALL_LIMIT
  const effectiveOffset = mode === 'grid' ? offset : 0

  // 当前用户在本表的权限（来自后端 current_user_actions）
  const userActions = table?.current_user_actions ?? []
  const hasAction = (a: string) => userActions.includes(a)
  const canEditSchema = hasAction('edit_schema')
  const canEditRecords = hasAction('edit_records')

  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 } } = useTableRecords(
    wid!, tid!, mode,
    {
      offset: effectiveOffset,
      limit: effectiveLimit,
      filters: effectiveFilters,
      sorts: sortsParam,
      filter_logic: viewFilterLogic,
    },
  )

  const deleteRows = useDeleteRowsOptimistic(wid!, tid!)
  const updateRow = useUpdateRowOptimistic(wid!, tid!)
  const copyRow = useMutation({
    mutationFn: async (ids: Array<number | string>) => {
      const copies: Array<Record<string, unknown>> = []
      for (const id of ids) {
        const r = rowList.items.find(x => x.id === id)
        if (r) {
          const { id: _skip, created_at: _c, updated_at: _u, created_by: _cb, updated_by: _ub, ...rest } = r
          copies.push(rest as Record<string, unknown>)
        }
      }
      if (copies.length === 0) return []
      const res = await recordApi.bulkCreate(wid!, tid!, copies)
      return res.ids
    },
    onSuccess: (ids) => {
      message.success(`已复制 ${ids.length} 行`)
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })
  // ── 行内新增（底部空白行）Mutation ──
  const createRow = useMutation({
    mutationFn: (values: RowValues) => recordApi.create(wid!, tid!, { values }),
    onSuccess: () => {
      message.success('已新增 1 行')
      setNewRowActive(false)
      setRowDrafts(prev => { const next = { ...prev }; delete next[NEW_ROW_KEY]; return next })
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '新增行失败')
    },
  })

  const gridFields = (table?.fields || []) as Field[]

  /** 依据原行（或空白）为每个可编辑字段初始化草稿 */
  const draftFor = (record: RowResponse | null): RowValues => {
    const d: RowValues = {}
    for (const f of gridFields) {
      if (!isEditableInlineField(f)) continue
      d[f.name] = normalizeCellValueForEdit(record ? record[f.name] : null, f)
    }
    return d
  }

  const updateDraft = (key: string, fieldName: string, value: unknown) => {
    setRowDrafts(prev => ({ ...prev, [key]: { ...(prev[key] ?? {}), [fieldName]: value } }))
  }

  const clearDraft = (key: string) => {
    setRowDrafts(prev => { const next = { ...prev }; delete next[key]; return next })
  }

  /** 激活底部空白新增行 */
  const startNewRow = () => {
    if (!canEditRecords) return
    setEditingRowId(null)
    setNewRowActive(true)
    setRowDrafts(prev => ({ ...prev, [NEW_ROW_KEY]: draftFor(null) }))
  }

  /** 进入某存量行的整行编辑态 */
  const startEditRow = (recordId: ID) => {
    setNewRowActive(false)
    const rec = rowList.items.find(r => String(r.id) === String(recordId)) ?? null
    setEditingRowId(recordId)
    setRowDrafts(prev => ({ ...prev, [rowKeyOf(recordId)]: draftFor(rec) }))
  }

  /** 取消某行编辑 / 放弃新增 */
  const cancelInline = (recordId: ID) => {
    const key = inlineDataKey(recordId)
    clearDraft(key)
    if (isNewRow(recordId)) setNewRowActive(false)
    else setEditingRowId(null)
  }

  /** 保存整行（新增建立 / 存量整行编辑提交） */
  const saveInline = (recordId: ID) => {
    const key = inlineDataKey(recordId)
    const draft = rowDrafts[key]
    if (!draft) return

    // 必填校验：可编辑必填字段最终值非空
    for (const f of gridFields) {
      if (!f.required || !isEditableInlineField(f)) continue
      if (isBlankCellValue(finalizeCellValue(draft[f.name], f))) {
        message.error(`请填写必填字段：${f.name}`)
        return
      }
    }

    // 仅提交非空的编辑字段
    const values: RowValues = {}
    for (const f of gridFields) {
      if (!isEditableInlineField(f)) continue
      const final = finalizeCellValue(draft[f.name], f)
      if (isBlankCellValue(final)) continue
      values[f.name] = final
    }

    if (isNewRow(recordId)) {
      createRow.mutate(values)
    } else {
      updateRow.mutate({ rowId: recordId, values }, {
        onSuccess: () => {
          setEditingRowId(null)
          clearDraft(rowKeyOf(recordId))
          message.success('已保存')
        },
      })
    }
  }

  /** 为指定行提供行内编辑能力（新增行激活 or 存量行整行编辑） */
  const getInlineEdit = useCallback((record: RowResponse): InlineEditCellProps | null => {
    const isNew = isNewRow(record.id)
    const editing = isNew ? newRowActive : (editingRowId != null && String(record.id) === String(editingRowId))
    if (!editing) return null
    const key = isNew ? NEW_ROW_KEY : rowKeyOf(record.id)
    return {
      editing: true,
      values: rowDrafts[key] ?? draftFor(record),
      onFieldChange: (fieldName, value) => updateDraft(key, fieldName, value),
      onFieldCommit: () => {}, // 行级统一保存，回车 noop
      onFieldCancel: () => { if (isNew) setNewRowActive(false); else setEditingRowId(null) },
    }
  }, [newRowActive, editingRowId, rowDrafts, gridFields]) // eslint-disable-line react-hooks/exhaustive-deps

  const inlineOps: RowInlineOps | undefined = canEditRecords ? {
    getInlineEdit,
    onEdit: startEditRow,
    onSave: saveInline,
    onCancel: cancelInline,
  } : undefined

  const createView = useMutation({
    mutationFn: (data: ViewCreate) => viewApi.create(wid!, tid!, data),
    onSuccess: () => {
      message.success('视图已创建')
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
    },
  })
  const importViews = useMutation({
    mutationFn: (data: ViewCreate[]) => viewApi.importViews(wid!, tid!, data),
    onSuccess: (created: View[]) => {
      message.success(`成功导入 ${created.length} 个视图`)
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
      setImportViewsOpen(false)
      setImportFile(null)
      setImportFileContent('')
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '导入失败')
    },
  })
  const updateView = useMutation({
    mutationFn: (args: {
      vid: number | string
      name?: string
      filters?: FilterRule[] | null
      sortings?: SortRule[] | null
      filter_type?: 'AND' | 'OR'
      view_type?: string
      view_options?: Record<string, unknown> | null
    }) =>
      viewApi.update(wid!, tid!, args.vid, {
        name: args.name,
        filters: args.filters ?? undefined,
        sortings: args.sortings ?? undefined,
        filter_type: args.filter_type ?? undefined,
        view_type: args.view_type,
        view_options: args.view_options ?? undefined,
      }),
    onSuccess: () => {
      message.success('视图已保存')
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '保存视图失败')
    },
  })
  const removeView = useMutation({
    mutationFn: (vid: number | string) => viewApi.remove(wid!, tid!, vid),
    onSuccess: () => {
      message.success('视图已删除')
      setActiveViewId(null)
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
    },
  })

  // ── 视图顺序拖拽 ──
  const viewDragSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  const reorderViews = useMutation({
    mutationFn: (ids: Array<number | string>) => viewApi.reorder(wid!, tid!, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
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
    const reordered = arrayMove(views, oldIndex, newIndex)
    reorderViews.mutate(reordered.map(v => v.id))
  }

  /** 持久化当前视图到后端（自动保存 useEffect 唯一真相源：viewFilters / viewSortings 等 state 变化自动触发）. */
  const persistCurrentView = () => {
    if (!activeViewId) return
    updateView.mutate({
      vid: activeViewId,
      filters: viewFilters.length ? viewFilters : null,
      sortings: viewSortings.length ? viewSortings : null,
      filter_type: viewFilterLogic,
      view_options: viewOptionsDraft,
    })
  }

  /** 右侧模式按钮组的统一处理：
   *  - 若当前激活视图已是目标类型 → 仅切换本地渲染模式.
   *  - 否则 → 跳到第一个 view_type 匹配的视图，让左侧 Segmented TAB 也联动选中.
   *  - 没有匹配类型的视图 → 仅切本地 mode（降级兜底，后端视图不变）.
   */
  const handleModeChange = (newMode: ViewMode) => {
    if (mode === newMode) return
    const _persistModeOnly = (m: ViewMode) => {
      setMode(m)
      try { localStorage.setItem(MODE_STORAGE_KEY, m) } catch { /* localStorage 不可用时忽略 */ }
      const params = new URLSearchParams(searchParams)
      params.set('mode', m)
      setSearchParams(params, { replace: true })
    }
    if (activeView?.view_type === newMode) {
      _persistModeOnly(newMode)
      return
    }
    const matchView = views.find(v => v.view_type === newMode)
    if (matchView) {
      loadView(matchView)
    } else {
      _persistModeOnly(newMode)
    }
  }

  /** 自动持久化视图配置（debounce 500ms） */
  useEffect(() => {
    if (!activeViewId || skipSaveRef.current) return
    const timer = setTimeout(() => persistCurrentView(), 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewFilters, viewSortings, viewFilterLogic, viewOptionsDraft, activeViewId])

  // 分享视图
  const shareView = useMutation({
    mutationFn: () => {
      const vid = activeViewId || (views.find(v => v.default)?.id) || (views[0]?.id)
      if (!vid) throw new Error('请先创建或选择一个视图')
      return viewApi.share(wid!, tid!, vid)
    },
    onSuccess: (res) => {
      message.success('分享已生成')
      // 自动复制到剪贴板
      navigator.clipboard?.writeText(res.share_url).then(() => message.info('分享链接已复制到剪贴板'))
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '分享失败'),
  })
  const revokeShare = useMutation({
    mutationFn: () => viewApi.revokeShare(wid!, tid!, activeViewId || views[0]?.id),
    onSuccess: () => message.success('已撤销分享'),
  })

  // 移动表
  const moveTable = useMutation({
    mutationFn: (targetWsId: number | string) => tableApi.move(wid!, tid!, targetWsId),
    onSuccess: () => {
      message.success('表已移动')
      setMoveOpen(false)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })

  // 复制表（三种模式）
  const copyTable = useMutation({
    mutationFn: (opts: { mode: 'structure' | 'all' | 'view'; viewId?: number | string }) =>
      tableApi.copy(wid!, tid!, opts),
    onSuccess: (t, opts) => {
      const modeLabel = opts.mode === 'structure' ? '(仅结构)' : opts.mode === 'view' ? '(当前视图)' : '(含全部数据)'
      message.success(`已复制为 "${t.name}" ${modeLabel}`, 2)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      if (t.id) setTimeout(() => navigate(`/w/${wid}/tables/${t.id}`), 300)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '复制失败'),
  })

  const columns = buildColumns(
    table?.fields || [], wid, viewSortings, viewFilters,
    (fieldName, op, value) => {
      // 替换同字段已有规则，没有则追加（避免不断累积）
      updateViewFilters(prev => {
        const without = prev.filter(f => f.field_name !== fieldName)
        return [...without, { field_name: fieldName, op, value }]
      })
      setOffset(0)
    },
    (fieldName) => {
      updateViewFilters(prev => prev.filter(f => f.field_name !== fieldName))
      setOffset(0)
    },
    updateRow.isPending
      ? undefined
      : (rowId, fieldName, value) => updateRow.mutateAsync({ rowId, fieldName, value }),
    inlineOps,
  )
  const numericFields = (table?.fields || []).filter(f => ['number', 'decimal'].includes(f.field_type))
  const selectedRows = (rowList.items || []).filter(r => selectedRowKeys.includes(r.id))
  const aggregates = useMemo(() => {
    const out: Record<string, { count: number; sum: number; avg: number }> = {}
    for (const f of numericFields) {
      let sum = 0, count = 0
      for (const r of selectedRows) {
        const col = f.name
        const v = Number(r[col])
        if (!Number.isNaN(v)) { sum += v; count++ }
      }
      if (count > 0) out[f.name] = { count, sum, avg: sum / count }
    }
    return out
  }, [selectedRows, numericFields])

  // 视图 Segmented 选项（支持拖拽排序）
  // 注意：loadView 未用 useCallback 包裹，随渲染重建；此处直接计算，避免 lint 缺依赖警告
  const segmentedOptions = views.map(v => ({
    label: (
      <DndViewTab
        view={v}
        active={activeViewId != null && String(v.id) === String(activeViewId)}
        onClick={() => loadView(v)}
      />
    ),
    value: String(v.id),
  }))

  /** 数据表实际拥有的视图类型集合（去重） */
  const availableViewTypes = useMemo<Set<ViewMode>>(() => {
    const s = new Set<ViewMode>()
    for (const v of views) {
      const vt = v.view_type as ViewMode | undefined
      if (vt && VALID_MODES.includes(vt)) s.add(vt)
    }
    // grid 作为基础视图，始终确保存在
    s.add('grid')
    return s
  }, [views])

  /** 右侧模式按钮组 —— 仅渲染数据表实际拥有的视图类型 */
  const modeButtons = useMemo(() =>
    MODE_BUTTONS.filter(b => availableViewTypes.has(b.mode)),
    [availableViewTypes])

  /** 是否渲染模式按钮组（多于一个按钮才显示；仅 grid 时隐藏） */
  const showModeSwitch = modeButtons.length > 1

  // 早 return — 已确保所有 hooks 调用完成
  if (!wid || !tid) return <Empty description="无效的表 ID" style={{ padding: 48 }} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* 顶部工具栏 */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--cn-border)', background: 'var(--cn-bg-container)', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}`)}>返回</Button>
        <Text strong style={{ fontSize: 16 }}>{table?.name || '...'}</Text>
        {/* 统计小徽标（来自后端增强字段） */}
        {table?.record_count != null && table.record_count > 0 && (
          <Tag color="blue" style={{ marginLeft: 4 }}>{table.record_count} 条记录</Tag>
        )}
        <div style={{ flex: 1 }} />
        <Space>
          <Tooltip title="表设置（字段/视图/权限）">
            <Button
              data-testid="table-settings-btn"
              icon={<MenuOutlined />}
              onClick={() => setTableSettingsOpen(true)}
            >
              表设置
            </Button>
          </Tooltip>
          <Button icon={<ImportOutlined />} onClick={() => setImportExportOpen(true)}>导入/导出</Button>
          <Dropdown menu={{
            items: [
              { key: 'refresh', icon: <ReloadOutlined />, label: '刷新', onClick: () => queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] }) },
              { type: 'divider' },
              { key: 'share', icon: <ShareAltOutlined />, label: '分享视图', onClick: () => shareView.mutate() },
              { key: 'revoke', icon: <CloseOutlined />, label: '撤销分享', onClick: () => revokeShare.mutate() },
              { type: 'divider' },
              { key: 'table-settings-page', icon: <SettingOutlined />, label: '表设置页面', onClick: () => navigate(`/w/${wid}/tables/${tid}/settings`) },
              { type: 'divider' },
              {
                key: 'copy', icon: <CopyOutlined />, label: '复制表',
                children: [
                  { key: 'copy-structure', label: '仅复制表结构', onClick: () => copyTable.mutate({ mode: 'structure' }) },
                  { key: 'copy-all', label: '复制表结构 + 全部数据', onClick: () => copyTable.mutate({ mode: 'all' }) },
                  {
                    key: 'copy-view',
                    label: `复制当前视图数据${activeView ? `（${activeView.name}）` : ''}`,
                    disabled: !activeView,
                    onClick: () => activeView && copyTable.mutate({ mode: 'view', viewId: activeView.id }),
                  },
                ],
              },
              { key: 'move', icon: <SwapOutlined />, label: '移动到其他工作区', onClick: () => setMoveOpen(true) },
              { type: 'divider' },
              {
                key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除表',
                disabled: !canEditSchema,
                onClick: () => Modal.confirm({
                  title: `删除表 "${table?.name}" ？`,
                  content: '表内所有记录和字段将被永久移除。此操作不可恢复。',
                  okText: '删除',
                  okType: 'danger',
                  cancelText: '取消',
                  onOk: () => tableApi.remove(wid!, tid!).then(() => {
                    message.success('表已删除')
                    queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
                    navigate(`/w/${wid}`)
                  }),
                }),
              },
            ]
          }}><Button icon={<MoreOutlined />} data-testid="grid-more-menu" /></Dropdown>
          <Button type="primary" icon={<PlusOutlined />} data-testid="add-row-btn" onClick={startNewRow} disabled={!canEditRecords}>新增行</Button>
        </Space>
      </div>

      {/* 视图切换 + 视图操作（支持拖拽排序） */}
      <div style={{ padding: '0 16px', background: 'var(--cn-bg-container)', borderBottom: '1px solid var(--cn-border)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <DndContext sensors={viewDragSensors} collisionDetection={closestCenter} onDragEnd={handleViewDragEnd}>
          <SortableContext items={views.map(v => String(v.id))} strategy={horizontalListSortingStrategy}>
            <Segmented
              value={activeViewId != null ? String(activeViewId) : undefined}
              onChange={(v) => {
                const key = String(v)
                loadView(views.find(vv => String(vv.id) === key) || null)
              }}
              options={segmentedOptions}
              style={{ flex: 1, overflow: 'auto' }}
            />
          </SortableContext>
        </DndContext>
        {/* 视图操作按钮组 */}
        <Space size={4}>
          <Tooltip title="新建视图">
            <Button size="small" type="text" icon={<PlusOutlined />} onClick={() => setCreateViewOpen(true)} />
          </Tooltip>
          <Tooltip title="编辑视图">
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              disabled={!activeView}
              onClick={() => setEditViewOpen(true)}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除此视图？"
            description={activeView?.name}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => activeViewId != null && removeView.mutate(String(activeViewId))}
            disabled={!activeView}
          >
            <Tooltip title="删除视图">
              <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={!activeView} />
            </Tooltip>
          </Popconfirm>
          <Tooltip title="导入视图">
            <Button
              size="small"
              type="text"
              icon={<ImportOutlined />}
              onClick={() => { setImportFile(null); setImportFileContent(''); setImportViewsOpen(true) }}
            />
          </Tooltip>
        </Space>
        {/* 视图模式切换 —— 仅渲染数据表实际拥有的视图类型；仅 grid 一种时隐藏 */}
        {showModeSwitch && (
          <Space.Compact>
            {modeButtons.map((b) => (
              <Tooltip key={b.mode} title={b.tooltip}>
                <Button
                  size="small"
                  type={mode === b.mode ? 'primary' : 'default'}
                  icon={b.icon}
                  data-mode={b.mode}
                  onClick={() => handleModeChange(b.mode)}
                />
              </Tooltip>
            ))}
          </Space.Compact>
        )}
        <Input.Search
          size="small"
          placeholder="搜索所有文本字段..."
          allowClear
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={e => { setSearchQuery(e.target.value); setOffset(0) }}
          style={{ width: 220 }}
        />
        <Tooltip title="当前视图筛选规则">
          <Button
            size="small"
            icon={<FilterOutlined />}
            type={viewFilters.length ? 'primary' : 'default'}
            onClick={() => setViewConfigOpen(true)}
          />
        </Tooltip>
        <Tooltip title="显示模式设置（对所有视图生效）">
          <Button
            size="small"
            icon={<SettingOutlined />}
            onClick={() => setSettingsOpen(true)}
          />
        </Tooltip>
      </div>

      {/* 主内容 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px', background: 'var(--cn-bg-page)' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
        ) : mode === 'grid' ? (
          <Table
            rowKey="id" className={`cn-table cn-table-${settings.density}`} size={densityToSize(settings.density)} loading={isLoading} columns={columns}
            dataSource={newRowActive ? [...(rowList.items || []), { id: NEW_ROW_KEY } as unknown as RowResponse] : (rowList.items || [])}
            bordered={settings.bordered}
            showHeader={settings.showHeader}
            rowClassName={settings.striped ? (_r, i) => (i % 2 === 1 ? 'table-row-striped' : '') : undefined}
            rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
            pagination={{
              current: Math.floor(offset / limit) + 1, pageSize: limit, total: rowList.total,
              showSizeChanger: true, pageSizeOptions: [25, 50, 100, 200],
              onChange: (p, l) => {
                setOffset((p - 1) * l)
                setLimit(l)
                // 预取下一页 —— 只有存在下一页且当前是 grid 模式（非全量拉取）时才预取
                const nextOffset = p * l
                if (mode === 'grid' && nextOffset < rowList.total) {
                  void queryClient.prefetchQuery({
                    queryKey: ['table-records', tableKey, mode, nextOffset, l, effectiveFilters ?? [], sortsParam ?? [], viewFilterLogic],
                    queryFn: () => recordApi.list(wid!, tid!, {
                      offset: nextOffset, limit: l,
                      filters: effectiveFilters?.length ? effectiveFilters : undefined,
                      sorts: sortsParam?.length ? sortsParam : undefined,
                      filter_logic: viewFilterLogic,
                    }),
                    staleTime: 10_000,
                  })
                }
              },
              showTotal: (t) => `共 ${t} 条`,
            }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 320px)' }}
            virtual
            onChange={(_pag, _fil, sorter, extra) => {
              // 只在用户点击列头排序时（extra.action === 'sort'）才处理排序，
              // 分页/筛选变化时 AntD 也会传当前排序状态，但不应触发 sort 处理逻辑
              if (extra?.action !== 'sort') {
                return
              }
              // 处理列排序 — Ant Design sorter 可能是单对象或数组
              // 受控排序循环：ascend → descend → null（清除）
              type SorterInfo = { field?: string | number | readonly (string | number)[]; order?: 'ascend' | 'descend' | null }
              const raw = sorter as SorterInfo | SorterInfo[] | null
              const items: SorterInfo[] = Array.isArray(raw) ? raw : (raw ? [raw] : [])
              const validItems = items.filter(it => typeof it?.field === 'string') as Array<{ field: string; order: 'ascend' | 'descend' | null }>
              if (validItems.length === 0) {
                return
              }
              const activeItem = validItems.find(it => it.order !== null) ?? validItems[0]
              const field = activeItem.field
              const order = activeItem.order
              if (order === null) {
                // 清除：只移除该字段的排序规则，保留其他
                updateViewSortings(prev => prev.filter(sr => sr.field_name !== field))
              } else {
                const newSort: SortRule = { field_name: field, direction: order === 'ascend' ? 'asc' : 'desc' }
                updateViewSortings(prev => {
                  const without = prev.filter(sr => sr.field_name !== field)
                  return [newSort, ...without]
                })
              }
              setOffset(0)
            }}
            onRow={(record) => (
              isNewRow(record.id) ? {} : ({ onDoubleClick: () => openDetailWithPrefetch(record) })
            )}
          />
        ) : mode === 'kanban' ? (
          <KanbanView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} sortings={viewSortings} onRowClick={openDetailWithPrefetch} />
        ) : mode === 'gallery' ? (
          <GalleryView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={openDetailWithPrefetch} />
        ) : mode === 'gantt' ? (
          <GanttView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} sortings={viewSortings} onRowClick={openDetailWithPrefetch} />
        ) : mode === 'wbs' ? (
          <WbsView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={openDetailWithPrefetch} />
        ) : (
          <CalendarView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={openDetailWithPrefetch} />
        )}
      </div>

      {/* 底部聚合条 */}
      {selectedRowKeys.length > 0 && (
        <div style={{ padding: '8px 16px', borderTop: '1px solid var(--cn-border)', background: 'var(--cn-bg-container)', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <Tag color="blue" style={{ margin: 0 }}>已选 {selectedRowKeys.length} 行</Tag>
          <Space size="middle">
            {Object.entries(aggregates).map(([name, a]) => (
              <Tag key={name} style={{ margin: 0 }}>{name}: {a.count}条 · 和 {a.sum.toFixed(2)} · 均值 {a.avg.toFixed(2)}</Tag>
            ))}
          </Space>
          <div style={{ marginLeft: 'auto' }}>
            <Space>
              <Button size="small" icon={<CopyOutlined />} loading={copyRow.isPending}
                onClick={() => copyRow.mutate(selectedRowKeys as Array<number | string>)}>复制选中</Button>
              <Button size="small" danger icon={<DeleteOutlined />}
                onClick={() => Modal.confirm({
                  title: `确定删除 ${selectedRowKeys.length} 行？`,
                  onOk: () => deleteRows.mutate(selectedRowKeys as Array<number | string>, {
                    onSuccess: () => { message.success('已删除'); setSelectedRowKeys([]) },
                  }),
                })}
                loading={deleteRows.isPending}>删除选中</Button>
              <Button size="small" onClick={() => setSelectedRowKeys([])}>取消选择</Button>
            </Space>
          </div>
        </div>
      )}

      {/* 抽屉 & 对话框 */}
      <RowDetailDrawer open={detailOpen} row={detailRow} fields={table?.fields || []} wid={wid} tid={tid}
        onClose={() => { setDetailOpen(false); setDetailRow(null) }} />
      <Suspense fallback={<ModalFallback />}>
        <FieldManager open={fieldMgrOpen} wid={wid} tid={tid} fields={table?.fields || []}
          onClose={() => setFieldMgrOpen(false)}
          onChanged={() => {
            queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
            queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
          }}
        />
        <ImportExportDialog open={importExportOpen} wid={wid} tid={tid}
          fields={table?.fields || []}
          onClose={() => setImportExportOpen(false)}
          onImported={() => {
            queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
            queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
          }}
        />
      </Suspense>
      <ViewConfigDialog
        open={viewConfigOpen}
        viewType={activeView?.view_type || 'grid'}
        filters={viewFilters}
        sortings={viewSortings}
        viewOptions={viewOptionsDraft}
        fields={table?.fields || []}
        onClose={() => setViewConfigOpen(false)}
        filterLogic={viewFilterLogic}
        onSaveFilterLogic={(logic) => { setViewFilterLogic(logic); setOffset(0) }}
        onSaveFilters={(f) => { setViewFilters(f); setOffset(0) }}
        onSaveSortings={(s) => { setViewSortings(s); setOffset(0) }}
        onSaveOptions={(o) => { setViewOptionsDraft(o) }}
      />

      {/* 创建新视图 Modal */}
      <Modal
        title="创建新视图"
        open={createViewOpen}
        onCancel={() => setCreateViewOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <CreateEditViewForm
          fields={table?.fields || []}
          submitLabel="创建"
          onSubmit={(name, vt, opts) => {
            const payload: { name: string; view_type: string; view_options?: Record<string, unknown> } = { name, view_type: vt }
            if (opts && Object.keys(opts).length) payload.view_options = opts
            createView.mutate(payload)
            setCreateViewOpen(false)
          }}
        />
      </Modal>

      {/* 编辑视图 Modal */}
      <Modal
        title="编辑视图"
        open={editViewOpen}
        onCancel={() => setEditViewOpen(false)}
        footer={null}
        destroyOnHidden
      >
        {activeView && (
          <CreateEditViewForm
            fields={table?.fields || []}
            initialName={activeView.name}
            initialType={activeView.view_type}
            initialOptions={activeView.view_options || undefined}
            submitLabel="保存"
            onSubmit={(name, vt, opts) => {
              const payload: { name: string; view_type: string; view_options?: Record<string, unknown> } = { name, view_type: vt }
              if (opts && Object.keys(opts).length) payload.view_options = opts
              updateView.mutate({ vid: activeView.id, ...payload })
              setEditViewOpen(false)
            }}
          />
        )}
      </Modal>

      {/* 导入视图 Modal */}
      <Modal
        title="导入视图"
        open={importViewsOpen}
        onCancel={() => setImportViewsOpen(false)}
        width={560}
        onOk={() => {
          if (!importFileContent) {
            message.warning('请先选择或拖入 JSON 文件')
            return
          }
          let parsed: ViewCreate[]
          try {
            parsed = JSON.parse(importFileContent)
            if (!Array.isArray(parsed)) throw new Error('JSON 根节点必须是数组')
          } catch (e) {
            message.error('JSON 解析失败: ' + (e instanceof Error ? e.message : String(e)))
            return
          }
          importViews.mutate(parsed)
        }}
        confirmLoading={importViews.isPending}
        okText="导入"
        cancelText="取消"
        okButtonProps={{ disabled: !importFileContent }}
      >
        <Upload.Dragger
          accept=".json,application/json"
          maxCount={1}
          fileList={importFile ? [{ uid: '-1', name: importFile.name, status: 'done' }] : []}
          beforeUpload={(file: File) => {
            const reader = new FileReader()
            reader.onload = () => {
              setImportFile(file)
              setImportFileContent(String(reader.result ?? ''))
            }
            reader.onerror = () => {
              message.error('读取文件失败')
              setImportFile(null)
              setImportFileContent('')
            }
            reader.readAsText(file, 'utf-8')
            return false
          }}
          onRemove={() => { setImportFile(null); setImportFileContent(''); return true }}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
          <p className="ant-upload-hint">支持 .json 格式，内容为视图配置数组</p>
        </Upload.Dragger>
        {importFile && (
          <div style={{ marginTop: 12, fontSize: 12, color: '#1677ff', textAlign: 'center' }}>
            已选择：{importFile.name}（{(importFile.size / 1024).toFixed(1)} KB）
          </div>
        )}
      </Modal>

      {/* 权限设置 Modal — 已收敛到 TableSettingsModal 的权限 Tab，仅作为 fallback 保留（不暴露按钮） */}
      {/* 移动表 Modal */}
      <Modal
        title="移动表到其他工作区"
        open={moveOpen}
        onCancel={() => setMoveOpen(false)}
        onOk={() => {
          const el = document.querySelector<HTMLSelectElement>('select[data-move-ws]')
          if (el?.value) moveTable.mutate(el.value)
        }}
        confirmLoading={moveTable.isPending}
        okText="移动"
      >
        <MoveTableForm currentWid={wid!} />
      </Modal>

      {/* 表格显示设置 Modal — 全局生效 */}
      <TableSettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onAfterSave={() => { setLimit(settings.defaultPageSize); setOffset(0) }}
      />

      {/* 新增行 & 整行编辑改用行内编辑（见 buildColumns inlineOps / 操作列），不再使用弹窗 */}

      {/* 表设置统一 Modal — 新增 */}
      <TableSettingsModal
        open={tableSettingsOpen}
        wid={wid!}
        tid={tid!}
        initialTab={tableSettingsTab}
        onClose={() => { setTableSettingsOpen(false); setTableSettingsTab('basic') }}
        onUpdated={() => {
          queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
          queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
          queryClient.invalidateQueries({ queryKey: ['table-settings', tableKey] })
        }}
      />
    </div>
  )
}

// ─────────────── 一些保留但暂隐藏的图标引用（让打包器知道没丢依赖） ───────────────
void CloseOutlined; void Switch

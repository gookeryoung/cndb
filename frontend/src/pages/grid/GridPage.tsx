/** Grid 主应用 — 集成视图 Tab / 四种视图 / inline 编辑 / 导入导出 / 行复制.
 *
 * 组件拆分说明（重构自 2400 行单体）:
 *   components/
 *     ├─ KanbanView.tsx         — 看板视图
 *     ├─ CalendarView.tsx       — 日历视图
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
import { Modal, Empty, App as AntApp } from 'antd'
import {
  ColumnHeightOutlined, AppstoreOutlined,
  CalendarOutlined, LineChartOutlined, PartitionOutlined,
} from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTable, useTableViews, useUpdateRowOptimistic, useDeleteRowsOptimistic } from '@/api/hooks'
import { arrayMove } from '@dnd-kit/sortable'
import type { DragEndEvent } from '@dnd-kit/core'
import { tableApi, recordApi, viewApi, auditApi } from '@/api'
import type { ID, RowValues, Field, RowResponse, View, ViewCreate } from '@/api'
import RowDetailDrawer from './layout/RowDetailDrawer'
import ViewConfigDialog, { type FilterRule, type SortRule } from './view-config/ViewConfigDialog'
import MoveTableForm from './layout/MoveTableForm'
import TableSettingsDialog from './view-config/TableSettingsDialog'
import TableSettingsModal from '@/pages/settings/TableSettingsModal'
import { buildColumns, type RowInlineOps, type InlineEditCellProps } from './cells/buildColumns'
import { useNewRowAutoScroll, type TableScrollTarget } from './cells/useNewRowAutoScroll'
import { finalizeCellValue, isBlankCellValue, isEditableInlineField, normalizeCellValueForEdit } from './cells/GridCell'
import { defaultValueForNewRow } from './cells/fieldOps'
import { type ViewMode, VALID_MODES, deriveModeSwitch } from './views/viewModes'
import { useTableSettingsStore, useGridViewStore } from '@/store'
import { useElementSize, useDebouncedCallback } from '@/hooks'
import GridToolbar from './gridToolbar'
import GridViewBar from './gridViewBar'
import GridTableSection, { NEW_ROW_KEY } from './gridTableSection'
import GridAggregationBar from './gridAggregationBar'
import GridViewModals from './gridViewModals'
import { useGridData } from './useGridData'

// Modal 组件 lazy import：点击打开时才加载
const FieldManager = lazy(() => import('@/pages/fields/FieldManager'))
const ImportExportDialog = lazy(() => import('@/pages/import-export/ImportExportDialog'))
// 非 grid 视图按 mode 懒加载：默认表格视图不下载看板/甘特/日历等代码
const KanbanView = lazy(() => import('./views/KanbanView'))
const CalendarView = lazy(() => import('./views/CalendarView'))
const GanttView = lazy(() => import('./views/GanttView'))
const WbsView = lazy(() => import('./views/WbsView'))

function ModalFallback() {
  return null
}

function ViewFallback() {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--cn-text-muted)', fontSize: 14 }}>
      视图加载中...
    </div>
  )
}

const MODE_STORAGE_KEY = 'cndb_current_mode'

/** 右侧模式按钮配置 —— 顺序即显示顺序；仅当数据表存在对应 view_type 的视图时才渲染. */
interface ModeBtn {
  mode: ViewMode
  tooltip: string
  icon: React.ReactNode
}
const MODE_BUTTONS: readonly ModeBtn[] = [
  { mode: 'grid', tooltip: '表格视图：行列结构，适合录入与批量管理', icon: <ColumnHeightOutlined /> },
  { mode: 'kanban', tooltip: '看板视图：按选择字段分组拖拽流转，适合任务跟踪', icon: <AppstoreOutlined /> },
  { mode: 'calendar', tooltip: '日历视图：按日期字段排布在月历上', icon: <CalendarOutlined /> },
  { mode: 'gantt', tooltip: '甘特图视图：时间轴展示任务起止与进度', icon: <LineChartOutlined /> },
  { mode: 'wbs', tooltip: 'WBS 视图：树状层级分解任务', icon: <PartitionOutlined /> },
]

/** 安全读取 localStorage（SSR / 隐私模式下可能抛异常）. */
function _readModeFromStorage(): ViewMode | null {
  try {
    const m = localStorage.getItem(MODE_STORAGE_KEY)
    if (m && (VALID_MODES as readonly string[]).includes(m)) return m as ViewMode
  } catch { /* localStorage 不可用时忽略 */ }
  return null
}

export default function GridPage() {
  const { message } = AntApp.useApp()
  const { wid, tid } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const density = useTableSettingsStore(s => s.density)
  const defaultPageSize = useTableSettingsStore(s => s.defaultPageSize)
  const bordered = useTableSettingsStore(s => s.bordered)
  const showHeader = useTableSettingsStore(s => s.showHeader)
  const striped = useTableSettingsStore(s => s.striped)
  const newRowPosition = useTableSettingsStore(s => s.newRowPosition)
  const autoFillLocked = useTableSettingsStore(s => s.autoFillLocked)
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
  /** 新建行 drawer 预填值（非 grid 视图下新增卡片时把分组字段预填好） */
  const [createInitialValues, setCreateInitialValues] = useState<RowValues | undefined>(undefined)
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
  /** 整行编辑模式下的行 id（null 表示无行处于整行编辑） */
  const [editingRowId, setEditingRowId] = useState<ID | null>(null)
  /** 底部空白新增行是否激活 */
  const [newRowActive, setNewRowActive] = useState(false)
  /** 各编辑态行的草稿值，key 为 `row-${id}`；新增行固定用 NEW_ROW_KEY */
  const [rowDrafts, setRowDrafts] = useState<Record<string, RowValues>>({})
  /** 新增行的锁定字段集合（自动填充预填的字段名集合） */
  const [newRowLockedFields, setNewRowLockedFields] = useState<Set<string>>(new Set())

  const rowKeyOf = (recordId: ID) => `row-${recordId}`
  const isNewRow = (recordId: ID) => String(recordId) === NEW_ROW_KEY
  const inlineDataKey = (recordId: ID) => (isNewRow(recordId) ? NEW_ROW_KEY : rowKeyOf(recordId))
  /** 表格容器尺寸测量（用于 scroll.y 精确数值计算）—— 通用 useElementSize 统一实现 */
  const [gridAreaRef, gridAreaSize] = useElementSize<HTMLDivElement>({ width: 800, height: 400 })
  /** AntD Table ref —— 暴露 scrollTo 方法，虚拟滚动场景下是唯一正确的滚动入口 */
  const tableRef = useRef<TableScrollTarget | null>(null)

  /** 切换视图 loadView 期间临时阻止自动保存（刚加载完的 state 不应立即回写）. */
  const skipSaveRef = useRef(false)

  /** 打开行详情抽屉并预取 audit/references —— queryKey 与 RowDetailDrawer 的自定义 hooks 完全一致. */
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
        queryKey: ['row-references', wid, tid, rowId],
        queryFn: () => tableApi.references(wid, tid, rowId),
        staleTime: 60_000,
      })
    }
  }, [wid, tid, queryClient])

  /** 打开新建行抽屉（非 grid 视图下新增卡片入口使用） */
  const openCreateDrawer = useCallback((initialValues?: RowValues) => {
    setCreateInitialValues(initialValues)
    setDetailRow(null)
    setDetailOpen(true)
  }, [])

  const { data: table, isLoading } = useTable(wid!, tid!)
  const { data: views = [] } = useTableViews(wid!, tid!)
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
      const KANBAN_MODES = new Set<string>(['kanban', 'calendar', 'gantt', 'wbs'])
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

  // 视图初始化 / 重新匹配：URL ?view= 深链 > 默认视图(is_default) > mode 兜底 > 第一个
  // 默认视图是「进入数据表的落地视图」：只要表存在默认视图，除 ?view= 深链外任何因素都不得覆盖它。
  // ?mode= / localStorage 仅在表缺少默认视图时兜底（正常情况下每张表都有「全部」默认视图）。
  // 每次 wid/tid/searchParams/views 变化时都重新评估，但只在目标和当前 activeViewId 不同时才切换，避免无限循环.
  useEffect(() => {
    if (!views.length) return

    // ── 计算最匹配的目标视图 ──
    let target: View | null = null

    // 1. URL 深链优先（精确 view id，分享 / 刷新直达指定视图）
    const vidParam = searchParams.get('view')
    if (vidParam) {
      target = views.find(v => String(v.id) === vidParam) || null
    }
    // 2. 默认视图 —— 进入数据表的落地视图
    if (!target) {
      target = views.find(v => v.is_default) || null
    }
    // 3. 兜底：URL mode / localStorage mode（仅表无默认视图时才会走到）
    if (!target) {
      const spMode = searchParams.get('mode') as ViewMode | null
      if (spMode && VALID_MODES.includes(spMode)) {
        target = views.find(v => v.view_type === spMode) || null
      }
      if (!target) {
        const lsMode = _readModeFromStorage()
        if (lsMode) target = views.find(v => v.view_type === lsMode) || null
      }
    }
    // 4. 最后退化为第一个视图
    if (!target) target = views[0] || null

    // ── 只在目标和当前不同时才切换（初始化不持久化 mode，避免污染 localStorage） ──
    if (target) {
      if (activeViewId !== String(target.id)) {
        loadView(target, false, false)
      }
    } else if (activeViewId !== null) {
      loadView(null, false, false)
    }
  }, [views, searchParams, wid, tid])  // eslint-disable-line react-hooks/exhaustive-deps

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

  // 当前生效的筛选/排序/分页参数 + 行数据（装配逻辑在 useGridData）
  const { effectiveFilters, sortsParam, rowList } = useGridData({
    wid, tid, mode, limit, offset, viewFilters, viewSortings, viewFilterLogic, searchQuery,
  })

  // 当前用户在本表的权限（来自后端 current_user_actions）
  const userActions = table?.current_user_actions ?? []
  const hasAction = (a: string) => userActions.includes(a)
  const canEditSchema = hasAction('edit_schema')
  const canEditRecords = hasAction('edit_records')

  /** 新增行激活后自动滚动聚焦 —— tail 跳页时以行数变化为重同步信号，数据到达后二次校准. */
  useNewRowAutoScroll({
    active: newRowActive,
    enabled: mode === 'grid',
    position: newRowPosition,
    rowDomKey: NEW_ROW_KEY,
    tableRef,
    resyncSignal: rowList.items?.length ?? 0,
  })

  const deleteRows = useDeleteRowsOptimistic(wid!, tid!)
  const updateRow = useUpdateRowOptimistic(wid!, tid!)

  /** 看板等视图删除单张卡片 */
  const handleDeleteCard = useCallback((r: RowResponse) => {
    deleteRows.mutate([r.id as number | string], {
      onSuccess: () => message.success('已删除'),
    })
  }, [deleteRows, message])

  /** 看板卡片勾选/取消完成 —— 直接把 done_field 目标值写回该行 */
  const handleToggleDone = useCallback((r: RowResponse, values: RowValues) => {
    updateRow.mutate({ rowId: r.id as number | string, values })
  }, [updateRow])
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
    onError: (err) => message.error(err instanceof Error ? err.message : '复制行失败'),
  })
  // ── 行内新增（底部空白行）Mutation ──
  const createRow = useMutation({
    mutationFn: (values: RowValues) => recordApi.create(wid!, tid!, { values }),
    onSuccess: () => {
      message.success('已新增 1 行')
      setNewRowActive(false)
      setNewRowLockedFields(new Set())
      setRowDrafts(prev => { const next = { ...prev }; delete next[NEW_ROW_KEY]; return next })
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '新增行失败')
    },
  })

  const gridFields = useMemo(() => (table?.fields || []) as Field[], [table?.fields])

  /** 计算自动预填锁定的字段集合（新增行场景下，autoFillLocked 开启时生效） */
  const computeLockedFields = useCallback(() => {
    if (!autoFillLocked) return new Set<string>()
    const locked = new Set<string>()
    for (const f of gridFields) {
      if (!isEditableInlineField(f)) continue
      const v = defaultValueForNewRow(f)
      if (v !== undefined) locked.add(f.name)
    }
    return locked
  }, [autoFillLocked, gridFields])

  /** 依据原行（或空白）为每个可编辑字段初始化草稿；新增行按 default_value / auto_fill 规则预填 */
  const draftFor = (record: RowResponse | null): RowValues => {
    const d: RowValues = {}
    for (const f of gridFields) {
      if (!isEditableInlineField(f)) continue
      d[f.name] = record ? normalizeCellValueForEdit(record[f.name], f) : defaultValueForNewRow(f)
    }
    return d
  }

  const updateDraft = (key: string, fieldName: string, value: unknown) => {
    setRowDrafts(prev => ({ ...prev, [key]: { ...(prev[key] ?? {}), [fieldName]: value } }))
  }

  const clearDraft = (key: string) => {
    setRowDrafts(prev => { const next = { ...prev }; delete next[key]; return next })
  }

  /** 激活底部空白新增行 —— 按 newRowPosition 自动跳转到能看见 newRow 的页.
   *  说明：Table 的 pagination 已设为 false（改用独立 Pagination 组件），
   *  Table 会完整渲染 dataSource（当前页数据 + newRow），不再被 AntD 客户端切片切掉 newRow.
   *  因此 'page'（页面尾部）无需翻页——newRow 直接追加在当前页数据末尾即可见；
   *  'top'/'tail' 需要先跳转到首页/末页，让 newRow 出现在表格首尾的正确位置. */
  const startNewRow = () => {
    if (!canEditRecords) return
    setEditingRowId(null)

    const currentTotal = rowList.total
    const currentLimit = limit
    let targetOffset: number | null = null

    if (newRowPosition === 'top') {
      // 表格顶部 — 跳到首页，newRow 会 prepend 在最前
      targetOffset = 0
    } else if (newRowPosition === 'tail') {
      // 表格尾部 — 跳到整个表格最后一页的起点，newRow 追加在该页末尾
      if (currentTotal === 0) {
        targetOffset = 0
      } else {
        targetOffset = Math.floor((currentTotal - 1) / currentLimit) * currentLimit
      }
    }
    // 'page'：页面尾部 — 直接追加到当前页末尾，Table 完整渲染 dataSource，newRow 立即可见，无需翻页

    if (targetOffset !== null && targetOffset !== offset) {
      setOffset(targetOffset)
    }

    setNewRowActive(true)
    setNewRowLockedFields(computeLockedFields())
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
    if (isNewRow(recordId)) { setNewRowActive(false); setNewRowLockedFields(new Set()) }
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
      onFieldCommit: () => { }, // 行级统一保存，回车 noop
      onFieldCancel: () => { if (isNew) setNewRowActive(false); else setEditingRowId(null) },
      // 仅新增行应用自动填充锁定；存量行整行编辑不受锁定限制
      lockedFields: isNew ? newRowLockedFields : new Set<string>(),
    }
  }, [newRowActive, editingRowId, rowDrafts, gridFields, newRowLockedFields]) // eslint-disable-line react-hooks/exhaustive-deps

  // 行内编辑桥接：最新操作集每次渲染同步写入 ref，对外只暴露引用稳定的 inlineOps。
  // 这样 buildColumns 的 useMemo 不会持有陈旧闭包（旧实现 deps 漏掉 inlineOps，
  // 草稿打字时 render 闭包可能读到旧 rowDrafts），高频更新也不重建整表列定义。
  const inlineOpsRef = useRef<RowInlineOps | null>(null)
  inlineOpsRef.current = canEditRecords
    ? { getInlineEdit, onEdit: startEditRow, onSave: saveInline, onCancel: cancelInline }
    : null

  const inlineOps = useMemo<RowInlineOps | undefined>(() => canEditRecords ? {
    getInlineEdit: (record) => inlineOpsRef.current?.getInlineEdit(record) ?? null,
    onEdit: (recordId) => { inlineOpsRef.current?.onEdit(recordId) },
    onSave: (recordId) => { inlineOpsRef.current?.onSave(recordId) },
    onCancel: (recordId) => { inlineOpsRef.current?.onCancel(recordId) },
  } : undefined, [canEditRecords])

  const createView = useMutation({
    mutationFn: (data: ViewCreate) => viewApi.create(wid!, tid!, data),
    onSuccess: () => {
      message.success('视图已创建')
      queryClient.invalidateQueries({ queryKey: ['table-views', tableKey] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建视图失败'),
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
    onError: (err) => message.error(err instanceof Error ? err.message : '删除视图失败'),
  })

  // ── 视图顺序拖拽 ──
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
  const persistCurrentView = useCallback(() => {
    if (!activeViewId) return
    updateView.mutate({
      vid: activeViewId,
      filters: viewFilters.length ? viewFilters : null,
      sortings: viewSortings.length ? viewSortings : null,
      filter_type: viewFilterLogic,
      view_options: viewOptionsDraft,
    })
  }, [activeViewId, viewFilters, viewSortings, viewFilterLogic, viewOptionsDraft, updateView])

  /** 立即保存视图（绕过 debounce）— 用于 ViewConfigDialog 保存按钮等显式保存场景 */
  const saveViewNow = useCallback(() => {
    cancelPersist()
    persistCurrentView()
  }, [cancelPersist, persistCurrentView])

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

  /** 自动持久化视图配置（debounce 500ms，防抖统一收敛到 useDebouncedCallback） */
  const [debouncedPersist, cancelPersist] = useDebouncedCallback(persistCurrentView, 500)
  useEffect(() => {
    if (!activeViewId || skipSaveRef.current) return
    debouncedPersist()
    // cleanup 取消 pending —— 与原手写 clearTimeout 语义一致（dep 变化即取消旧计时器）
    return cancelPersist
  }, [viewFilters, viewSortings, viewFilterLogic, viewOptionsDraft, activeViewId, debouncedPersist, cancelPersist])

  // 移动表
  const moveTable = useMutation({
    mutationFn: (targetWsId: number | string) => tableApi.move(wid!, tid!, targetWsId),
    onSuccess: () => {
      message.success('表已移动')
      setMoveOpen(false)
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '移动表失败'),
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

  const _onFilterApply = useCallback((fieldName: string, op: string, value: unknown) => {
    updateViewFilters(prev => {
      const without = prev.filter(f => f.field_name !== fieldName)
      return [...without, { field_name: fieldName, op, value }]
    })
    setOffset(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateViewFilters])
  const _onFilterReset = useCallback((fieldName: string) => {
    updateViewFilters(prev => prev.filter(f => f.field_name !== fieldName))
    setOffset(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateViewFilters])
  const _onCellSave = useMemo(() => updateRow.isPending
    ? undefined
    : (rowId: number | string, fieldName: string, value: unknown) => updateRow.mutateAsync({ rowId, fieldName, value }),
    [updateRow])

  const columns = useMemo(() => buildColumns(
    table?.fields || [], wid, viewSortings, viewFilters,
    _onFilterApply,
    _onFilterReset,
    _onCellSave,
    inlineOps,
  ), [table?.fields, wid, viewSortings, viewFilters, _onFilterApply, _onFilterReset, _onCellSave, inlineOps])

  // 选中行聚合：过滤与计算收敛到同一个 useMemo。
  // 旧实现的 numericFields / selectedRows 每次渲染都是新数组，使本 memo 依赖恒变、缓存完全失效。
  // 选中键用 Set 查询，顺带把原来的 O(行数 × 选中数) includes 降为 O(行数)。
  const aggregates = useMemo(() => {
    const numericFields = (table?.fields || []).filter(
      f => f.field_type === 'number' || f.field_type === 'decimal',
    )
    if (numericFields.length === 0 || selectedRowKeys.length === 0) return {}
    const selectedKeySet = new Set(selectedRowKeys)
    const selectedRows = (rowList.items || []).filter(r => selectedKeySet.has(r.id))
    const out: Record<string, { count: number; sum: number; avg: number }> = {}
    for (const f of numericFields) {
      let sum = 0, count = 0
      for (const r of selectedRows) {
        const v = Number(r[f.name])
        if (!Number.isNaN(v)) { sum += v; count++ }
      }
      if (count > 0) out[f.name] = { count, sum, avg: sum / count }
    }
    return out
  }, [table?.fields, rowList.items, selectedRowKeys])

  /** 右侧模式按钮组 —— 仅渲染数据表实际拥有的视图类型；仅 grid 时隐藏（推导逻辑在 viewModes.ts，纯函数可单测） */
  const { buttons: modeButtons, visible: showModeSwitch } = useMemo(
    () => deriveModeSwitch(views, MODE_BUTTONS),
    [views],
  )

  // 早 return — 已确保所有 hooks 调用完成
  if (!wid || !tid) return <Empty description="无效的表 ID" style={{ padding: 48 }} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* 顶部工具栏 */}
      <GridToolbar
        wid={wid!}
        tid={tid!}
        tableKey={tableKey}
        tableName={table?.name}
        recordCount={table?.record_count}
        mode={mode}
        addRowDisabled={!canEditRecords || newRowActive || editingRowId != null}
        onAddRow={startNewRow}
        canEditSchema={canEditSchema}
        onOpenTableSettings={() => setTableSettingsOpen(true)}
        onOpenImportExport={() => setImportExportOpen(true)}
        activeViewName={activeView?.name}
        activeViewId={activeView?.id}
        onCopyTable={(opts) => copyTable.mutate(opts)}
        onMove={() => setMoveOpen(true)}
      />

      {/* 视图切换 + 操作栏（支持拖拽排序） */}
      <GridViewBar
        wid={wid!}
        tid={tid!}
        views={views}
        activeViewId={activeViewId}
        mode={mode}
        modeButtons={modeButtons}
        showModeSwitch={showModeSwitch}
        hasFilters={viewFilters.length > 0}
        hasSorts={viewSortings.length > 0}
        searchQuery={searchQuery}
        onSearchChange={(q) => { setSearchQuery(q); setOffset(0) }}
        onSelectView={(v) => loadView(v)}
        onModeChange={handleModeChange}
        onDragEnd={handleViewDragEnd}
        onCreate={() => setCreateViewOpen(true)}
        onEdit={() => setEditViewOpen(true)}
        onDelete={() => activeViewId != null && removeView.mutate(String(activeViewId))}
        onImport={() => { setImportFile(null); setImportFileContent(''); setImportViewsOpen(true) }}
        onOpenViewConfig={() => setViewConfigOpen(true)}
        onOpenDisplaySettings={() => setSettingsOpen(true)}
      />

      {/* 主内容 — flex:1 占满剩余空间，overflow:hidden 交给内部 Table 的虚拟滚动 */}
      <div ref={gridAreaRef} style={{ flex: 1, minHeight: 0, padding: '12px 16px', background: 'var(--cn-bg-page)', display: 'flex', flexDirection: 'column' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
        ) : mode === 'grid' ? (
          <GridTableSection
            tableRef={tableRef}
            columns={columns}
            settings={{ density, bordered, showHeader, striped }}
            isLoading={isLoading}
            rows={rowList.items || []}
            total={rowList.total}
            newRowActive={newRowActive}
            newRowPosition={newRowPosition}
            canEditRecords={canEditRecords}
            selectedRowKeys={selectedRowKeys}
            onSelectionChange={setSelectedRowKeys}
            onAddRow={startNewRow}
            onRowDoubleClick={openDetailWithPrefetch}
            onSort={(field, direction) => {
              if (direction === null) {
                // 清除：只移除该字段的排序规则，保留其他
                updateViewSortings(prev => prev.filter(sr => sr.field_name !== field))
              } else {
                const newSort: SortRule = { field_name: field, direction }
                updateViewSortings(prev => {
                  const without = prev.filter(sr => sr.field_name !== field)
                  return [newSort, ...without]
                })
              }
              setOffset(0)
            }}
            gridAreaSize={gridAreaSize}
            offset={offset}
            limit={limit}
            onPageChange={(p, l) => { setOffset((p - 1) * l); setLimit(l) }}
            prefetchNext={(nextOffset, l) => {
              // 预取下一页 —— 只有存在下一页且当前是 grid 模式（非全量拉取）时才预取
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
            }}
          />
        ) : (
          <Suspense fallback={<ViewFallback />}>
            {mode === 'kanban' ? (
              <KanbanView
                rows={rowList.items || []}
                fields={table?.fields || []}
                view={activeView}
                density={settings.density}
                sortings={viewSortings}
                onRowClick={openDetailWithPrefetch}
                onDeleteCard={handleDeleteCard}
                canDelete={canEditRecords}
                onAddCard={openCreateDrawer}
                canAdd={canEditRecords}
                onToggleDone={handleToggleDone}
                canEdit={canEditRecords}
              />
            ) : mode === 'gantt' ? (
              <GanttView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} sortings={viewSortings} onRowClick={openDetailWithPrefetch} />
            ) : mode === 'wbs' ? (
              <WbsView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={openDetailWithPrefetch} />
            ) : (
              <CalendarView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={openDetailWithPrefetch} />
            )}
          </Suspense>
        )}
      </div>

      {/* 底部聚合条 */}
      <GridAggregationBar
        selectedCount={selectedRowKeys.length}
        aggregates={aggregates}
        copyLoading={copyRow.isPending}
        deleteLoading={deleteRows.isPending}
        onCopy={() => copyRow.mutate(selectedRowKeys as Array<number | string>)}
        onDelete={() => deleteRows.mutate(selectedRowKeys as Array<number | string>, {
          onSuccess: () => { message.success('已删除'); setSelectedRowKeys([]) },
        })}
        onClear={() => setSelectedRowKeys([])}
      />

      {/* 抽屉 & 对话框 */}
      {detailOpen && (
        <RowDetailDrawer
          open={detailOpen}
          row={detailRow}
          fields={table?.fields || []}
          wid={wid}
          tid={tid}
          initialValues={createInitialValues}
          onClose={() => {
            setDetailOpen(false)
            setDetailRow(null)
            setCreateInitialValues(undefined)
          }}
        />
      )}
      <Suspense fallback={<ModalFallback />}>
        {fieldMgrOpen && (
          <FieldManager open={fieldMgrOpen} wid={wid} tid={tid} fields={table?.fields || []}
            onClose={() => setFieldMgrOpen(false)}
            onChanged={() => {
              queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
              queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
            }}
          />
        )}
        {importExportOpen && (
          <ImportExportDialog open={importExportOpen} wid={wid} tid={tid}
            fields={table?.fields || []}
            onClose={() => setImportExportOpen(false)}
            onImported={() => {
              queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
              queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
            }}
          />
        )}
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
        onSaveNow={saveViewNow}
      />

      {/* 创建 / 编辑 / 导入视图 Modal 组 */}
      <GridViewModals
        fields={table?.fields || []}
        activeView={activeView}
        createOpen={createViewOpen}
        onCloseCreate={() => setCreateViewOpen(false)}
        editOpen={editViewOpen}
        onCloseEdit={() => setEditViewOpen(false)}
        importOpen={importViewsOpen}
        onCloseImport={() => setImportViewsOpen(false)}
        onCreate={(payload) => { createView.mutate(payload); setCreateViewOpen(false) }}
        onEditSave={(vid, payload) => { updateView.mutate({ vid, ...payload }); setEditViewOpen(false) }}
        onImport={(parsed) => importViews.mutate(parsed)}
        importPending={importViews.isPending}
        importFile={importFile}
        importFileContent={importFileContent}
        onImportFileChange={(f, content) => { setImportFile(f); setImportFileContent(content) }}
      />

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

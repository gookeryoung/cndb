/** Grid 主应用 — 集成视图 Tab / 三种视图 / inline 编辑 / 导入导出 / 行复制. */

import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Table, Button, Space, Tag, Modal, Typography, message, Tooltip, Dropdown, Empty, Row, Col, Badge, Input, InputNumber, Segmented, Tabs, Select, Form, Switch, Upload, Popconfirm } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, ColumnHeightOutlined,
  FilterOutlined, MoreOutlined, ArrowLeftOutlined, EyeOutlined, SettingOutlined,
  AppstoreOutlined, CopyOutlined, ImportOutlined, UploadOutlined, DownOutlined, CloseOutlined,
  CalendarOutlined, ShareAltOutlined, SafetyOutlined, SwapOutlined,
  SearchOutlined, SortAscendingOutlined, SortDescendingOutlined, EditOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi, viewApi, permissionApi, userApi } from '@/api'
import type { RowResponse, Field, TableDetail, View, ViewCreate, TablePermission } from '@/api'
import GridCell from './components/GridCell'
import RowDetailDrawer from './components/RowDetailDrawer'
import KanbanView from './components/KanbanView'
import CalendarView from './components/CalendarView'
import { useTableSettings } from '@/theme/TableSettingsProvider'
import { densityToSize, DEFAULT_TABLE_SETTINGS, type Density } from '@/theme/tableSettings'

// Modal 组件 lazy import：点击打开时才加载
const FieldManager = lazy(() => import('@/pages/modals/FieldManager'))
const ImportExportDialog = lazy(() => import('@/pages/modals/ImportExportDialog'))

function ModalFallback() {
  return null
}

const { Text } = Typography
type ViewMode = 'grid' | 'kanban' | 'gallery' | 'calendar'
const VALID_MODES: readonly ViewMode[] = ['grid', 'kanban', 'gallery', 'calendar']
const MODE_STORAGE_KEY = 'cndb_current_mode'

/** 安全读取 localStorage（SSR / 隐私模式下可能抛异常）. */
function _readModeFromStorage(): ViewMode | null {
  try {
    const m = localStorage.getItem(MODE_STORAGE_KEY)
    if (m && (VALID_MODES as readonly string[]).includes(m)) return m as ViewMode
  } catch { /* localStorage 不可用时忽略 */ }
  return null
}

export default function GridPage() {
  const { wid, tid } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { settings } = useTableSettings()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [mode, setMode] = useState<ViewMode>(() => {
    const spMode = searchParams.get('mode') as ViewMode | null
    if (spMode && (VALID_MODES as readonly string[]).includes(spMode)) return spMode
    const lsMode = _readModeFromStorage()
    return lsMode ?? 'grid'
  })
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
  const [permOpen, setPermOpen] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [activeViewId, setActiveViewId] = useState<number | string | null>(null)
  const [viewFilters, setViewFilters] = useState<Array<{ field_name: string; op: string; value?: unknown }>>([])
  const [viewSortings, setViewSortings] = useState<Array<{ field_name: string; direction: 'asc' | 'desc' }>>([])
  const [viewFilterLogic, setViewFilterLogic] = useState<'AND' | 'OR'>('AND')
  const [viewOptionsDraft, setViewOptionsDraft] = useState<Record<string, unknown> | null>(null)
  const [searchQuery, setSearchQuery] = useState<string>(() => searchParams.get('q') || '')
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(settings.defaultPageSize)
  const tableKey = `${wid}/${tid}`

  /** 切换视图 loadView 期间临时阻止自动保存（刚加载完的 state 不应立即回写）. */
  const skipSaveRef = useRef(false)

  const { data: table, isLoading } = useQuery<TableDetail>({
    queryKey: ['table', tableKey],
    queryFn: () => tableApi.get(wid!, tid!),
    enabled: !!wid && !!tid,
  })
  const { data: views = [] } = useQuery<View[]>({
    queryKey: ['table-views', tableKey],
    queryFn: () => viewApi.list(wid!, tid!),
    enabled: !!wid && !!tid,
  })
  /** 用户偏好：当前表的激活视图 ID（per-user per-table 持久化） */
  const { data: activeViewPreference } = useQuery<{ table_id: number; active_view_id: number | null }>({
    queryKey: ['user-pref-active-view', tableKey],
    queryFn: () => userApi.getTableActiveView(tid!),
    enabled: !!wid && !!tid,
    staleTime: 60_000,
  })
  /** 保存激活视图偏好（debounce 在 loadView 里手动控制） */
  const saveActiveViewPref = useMutation({
    mutationFn: (vid: number | null) => userApi.setTableActiveView(Number(tid!), vid),
  })
  /** 把后端存储的 filters（dict 或 list）归一化成 list 形式 */
  function normalizeFilters(raw: unknown): Array<{ field_name: string; op: string; value?: unknown }> {
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
      const result: Array<{ field_name: string; op: string; value?: unknown }> = []
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
  const loadView = (v: View | null, updateUrl = true) => {
    skipSaveRef.current = true // 切换视图期间阻止自动保存
    if (v) {
      setActiveViewId(v.id)
      setViewFilters(normalizeFilters(v.filters))
      setViewSortings(Array.isArray(v.sortings) ? v.sortings : [])
      setViewFilterLogic((v.filter_type ?? 'AND') as 'AND' | 'OR')
      setViewOptionsDraft(v.view_options ?? null)
      const newMode = (['kanban', 'gallery', 'calendar'] as const).includes(v.view_type as ViewMode)
        ? (v.view_type as ViewMode)
        : 'grid'
      setMode(newMode)
      // 全局模式持久化（localStorage + URL）—— 跨表切换时自动找回相同视图类型
      try { localStorage.setItem(MODE_STORAGE_KEY, newMode) } catch { /* localStorage 不可用时忽略 */ }
      if (updateUrl) {
        const params = new URLSearchParams(searchParams)
        params.set('view', String(v.id))
        params.set('mode', newMode)
        setSearchParams(params, { replace: true })
        // 用户主动切换视图 —— 持久化偏好到后端
        saveActiveViewPref.mutate(Number(v.id))
      }
    } else {
      setActiveViewId(null)
      setViewFilters([])
      setViewSortings([])
      setViewFilterLogic('AND')
      setViewOptionsDraft(null)
      setMode('grid')
      try { localStorage.setItem(MODE_STORAGE_KEY, 'grid') } catch { /* localStorage 不可用时忽略 */ }
      if (updateUrl) {
        const params = new URLSearchParams(searchParams)
        params.delete('view')
        params.delete('mode')
        setSearchParams(params, { replace: true })
      }
    }
    setOffset(0)
    // 等 React 批量 setState 渲染完，下一轮微任务允许自动保存
    queueMicrotask(() => { skipSaveRef.current = false })
  }

  // 当前激活的视图对象（含 view_options）
  const activeView = activeViewId != null ? views.find(v => String(v.id) === String(activeViewId)) : null

  // 视图初始化：URL ?view= 深链 > URL ?mode= 匹配 > localStorage mode 匹配 > 用户偏好 active_view_id > is_default > 第一个
  useEffect(() => {
    if (!views.length || activeViewId !== null) return
    // 1. URL 深链优先（精确 view id）
    const vidParam = searchParams.get('view')
    if (vidParam) {
      const target = views.find(v => String(v.id) === vidParam)
      if (target) { loadView(target, false); return }
    }
    // 2. URL mode 匹配（刷新 / 从其它表带 ?mode= 导航过来时保留展示模式）
    const spMode = searchParams.get('mode') as ViewMode | null
    if (spMode && VALID_MODES.includes(spMode)) {
      const target = views.find(v => v.view_type === spMode)
      if (target) { loadView(target, false); return }
    }
    // 3. localStorage mode 匹配（侧边栏点表导航丢失 URL 参数时的兜底）
    const lsMode = _readModeFromStorage()
    if (lsMode) {
      const target = views.find(v => v.view_type === lsMode)
      if (target) { loadView(target, false); return }
    }
    // 4. 用户偏好的激活视图（后端存储 per-table）
    const prefVid = activeViewPreference?.active_view_id
    if (prefVid != null) {
      const target = views.find(v => Number(v.id) === prefVid)
      if (target) { loadView(target, false); return }
    }
    // 5. 最后：default 或第一个
    const def = views.find(v => v.default) || views[0]
    if (def) loadView(def, false)
    else setActiveViewId(null)
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
    const list: Array<Record<string, unknown>> = [...viewFilters]
    if (searchQuery.trim()) list.push({ field_name: '__query__', op: 'contains', value: searchQuery.trim() })
    return list.length ? list : undefined
  }, [viewFilters, searchQuery])

  // 当前生效的排序条件
  const sortsParam = useMemo(() => {
    return viewSortings.length ? viewSortings : undefined
  }, [viewSortings])

  // 非 grid 视图需要全量数据（日历/看板/画廊要跨月/跨列聚合），绕过分页
  const VIEW_FETCH_ALL_LIMIT = 5000
  const effectiveLimit = mode === 'grid' ? limit : VIEW_FETCH_ALL_LIMIT
  const effectiveOffset = mode === 'grid' ? offset : 0

  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 } } = useQuery({
    queryKey: ['table-records', tableKey, mode, effectiveOffset, effectiveLimit, effectiveFilters, sortsParam, viewFilterLogic],
    queryFn: () => {
      return recordApi.list(wid!, tid!, { offset: effectiveOffset, limit: effectiveLimit, filters: effectiveFilters, sorts: sortsParam, filter_logic: viewFilterLogic })
    },
    enabled: !!wid && !!tid,
  })

  const deleteRows = useMutation({
    mutationFn: (ids: React.Key[]) => recordApi.bulkDelete(wid!, tid!, ids as Array<number | string>),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
      setSelectedRowKeys([])
    },
  })
  const quickAdd = useMutation({
    mutationFn: () => recordApi.create(wid!, tid!, { values: {} }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })
  const updateRow = useMutation({
    mutationFn: async (args: { rowId: number | string; fieldName: string; value: unknown }) => {
      const payload: Record<string, unknown> = { [args.fieldName]: args.value }
      return recordApi.update(wid!, tid!, args.rowId, { values: payload })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] })
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '保存失败')
    },
  })
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
      filters?: Array<{ field_name: string; op: string; value?: unknown }> | null
      sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
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
   *  - 若当前激活视图已是目标类型 → 仅切换本地渲染模式（边界，正常不触发）.
   *  - 否则 → 跳到第一个 view_type 匹配的视图，让左侧 Segmented TAB 也联动选中.
   *  - 没有匹配类型的视图 → 仅切本地 mode（降级兜底，后端视图不变）.
   *
   *  形成双向联动：
   *    Segmented 点选 → loadView 根据 view_type 自动同步 ButtonGroup 高亮（已有）.
   *    ButtonGroup 点击 → 本函数跳到目标视图，Segmented 选中项同步变化（本次修复）.
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
    // 当前视图已是此类型 — 理论上不会进入（mode 有 guard），兜底直接切
    if (activeView?.view_type === newMode) {
      _persistModeOnly(newMode)
      return
    }
    // 找第一个 view_type 匹配的视图
    const matchView = views.find(v => v.view_type === newMode)
    if (matchView) {
      // loadView 会同时：更新 activeViewId（Segmented 选中项）+ setMode（ButtonGroup 高亮）+ 持久化 URL + localStorage
      loadView(matchView)
    } else {
      // 没有匹配类型的视图，降级只切渲染（无视图可联动）—— 但仍持久化 mode 供后续跨表匹配
      _persistModeOnly(newMode)
    }
  }

  /** 自动持久化视图配置（debounce 500ms）: 列头筛选/排序、ViewConfigDialog 保存等所有 state 变更均走此入口.
   *  切换视图 loadView 期间 skipSaveRef=true，刚加载完的 state 不会触发无意义的回写.
   */
  useEffect(() => {
    if (!activeViewId || skipSaveRef.current) return
    const timer = setTimeout(() => persistCurrentView(), 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewFilters, viewSortings, viewFilterLogic, viewOptionsDraft, activeViewId])

  // 权限查询（点开权限 Modal 时加载）
  const { data: permData, refetch: refetchPerm } = useQuery<TablePermission>({
    queryKey: ['table-perm', tableKey],
    queryFn: () => permissionApi.get(wid!, tid!),
    enabled: false,
  })
  const savePerm = useMutation({
    mutationFn: (data: Partial<TablePermission>) => permissionApi.patch(wid!, tid!, data),
    onSuccess: () => {
      message.success('权限已更新')
      setPermOpen(false)
    },
  })

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
      queryClient.invalidateQueries({ queryKey: ['table', tableKey] })
    },
  })

  const columns = buildColumns(table?.fields || [], wid, viewSortings, viewFilters,
    (fieldName, op, value) => {
      // 替换同字段已有规则，没有则追加（避免不断累积）
      setViewFilters(prev => {
        const without = prev.filter(f => f.field_name !== fieldName)
        return [...without, { field_name: fieldName, op, value }]
      })
      setOffset(0)
    },
    (fieldName) => {
      setViewFilters(prev => prev.filter(f => f.field_name !== fieldName))
      setOffset(0)
    },
    updateRow.isPending
      ? undefined
      : (rowId, fieldName, value) => updateRow.mutateAsync({ rowId, fieldName, value }),
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

  // 视图 Segmented 选项（仅来自后端定义的视图，不再硬编码"全部"避免与"全部XX"默认视图冗余）
  const segmentedOptions = useMemo(() => views.map(v => ({
    label: (
      <span>
        {v.name}
        {v.default && <Tag color="blue" style={{ marginLeft: 4, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>默认</Tag>}
      </span>
    ),
    value: String(v.id),
  })), [views])

  // 早 return — 已确保所有 hooks 调用完成
  if (!wid || !tid) return <Empty description="无效的表 ID" style={{ padding: 48 }} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* 顶部工具栏 */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #e5e7eb', background: '#fff', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}`)}>返回</Button>
        <Text strong style={{ fontSize: 16 }}>{table?.name || '...'}</Text>
        <div style={{ flex: 1 }} />
        <Space>
          <Tooltip title="字段管理"><Button icon={<SettingOutlined />} onClick={() => setFieldMgrOpen(true)} /></Tooltip>
          <Button icon={<ImportOutlined />} onClick={() => setImportExportOpen(true)}>导入/导出</Button>
          <Dropdown menu={{
            items: [
              { key: 'refresh', icon: <ReloadOutlined />, label: '刷新', onClick: () => queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] }) },
              { key: 'perm', icon: <SafetyOutlined />, label: '权限设置', onClick: () => { refetchPerm(); setPermOpen(true) } },
              { key: 'share', icon: <ShareAltOutlined />, label: '分享视图', onClick: () => shareView.mutate() },
              { key: 'revoke', icon: <CloseOutlined />, label: '撤销分享', onClick: () => revokeShare.mutate() },
              { type: 'divider' },
              { key: 'copy', icon: <CopyOutlined />, label: '复制表', onClick: () => tableApi.copy(wid!, tid!).then(() => message.success('表已复制')).then(() => queryClient.invalidateQueries({ queryKey: ['table', tableKey] })) },
              { key: 'move', icon: <SwapOutlined />, label: '移动到其他工作区', onClick: () => setMoveOpen(true) },
              { type: 'divider' },
              { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除表', disabled: true },
            ]
          }}><Button icon={<MoreOutlined />} /></Dropdown>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => quickAdd.mutate()}>新增行</Button>
        </Space>
      </div>

      {/* 视图切换 + 视图操作 */}
      <div style={{ padding: '0 16px', background: '#fff', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Segmented
          value={activeViewId != null ? String(activeViewId) : undefined}
          onChange={(v) => {
            const key = String(v)
            loadView(views.find(vv => String(vv.id) === key) || null)
          }}
          options={segmentedOptions}
          style={{ flex: 1, overflow: 'auto' }}
        />
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
        {/* 视图模式切换（无文字） */}
        <Space.Compact>
          <Tooltip title="表格">
            <Button size="small" type={mode === 'grid' ? 'primary' : 'default'} icon={<ColumnHeightOutlined />} onClick={() => handleModeChange('grid')} />
          </Tooltip>
          <Tooltip title="看板">
            <Button size="small" type={mode === 'kanban' ? 'primary' : 'default'} icon={<AppstoreOutlined />} onClick={() => handleModeChange('kanban')} />
          </Tooltip>
          <Tooltip title="画廊">
            <Button size="small" type={mode === 'gallery' ? 'primary' : 'default'} icon={<EyeOutlined />} onClick={() => handleModeChange('gallery')} />
          </Tooltip>
          <Tooltip title="日历">
            <Button size="small" type={mode === 'calendar' ? 'primary' : 'default'} icon={<CalendarOutlined />} onClick={() => handleModeChange('calendar')} />
          </Tooltip>
        </Space.Compact>
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
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px', background: '#fafafa' }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>加载中...</div>
        ) : mode === 'grid' ? (
          <Table
            rowKey="id" className={`cn-table cn-table-${settings.density}`} size={densityToSize(settings.density)} loading={isLoading} columns={columns} dataSource={rowList.items || []}
            bordered={settings.bordered}
            showHeader={settings.showHeader}
            rowClassName={settings.striped ? (_r, i) => (i % 2 === 1 ? 'table-row-striped' : '') : undefined}
            rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
            pagination={{
              current: Math.floor(offset / limit) + 1, pageSize: limit, total: rowList.total,
              showSizeChanger: true, pageSizeOptions: [25, 50, 100, 200],
              onChange: (p, l) => { setOffset((p - 1) * l); setLimit(l) },
              showTotal: (t) => `共 ${t} 条`,
            }}
            scroll={{ x: 'max-content' }}
            onChange={(_pag, _fil, sorter) => {
              // 处理列排序 — Ant Design sorter 可能是单对象或数组
              // 受控排序循环：ascend → descend → null（清除）
              type SorterInfo = { field?: string | number | readonly (string | number)[]; order?: 'ascend' | 'descend' | null }
              const raw = sorter as SorterInfo | SorterInfo[] | null
              // 统一转成数组
              const items: SorterInfo[] = Array.isArray(raw) ? raw : (raw ? [raw] : [])
              // 过滤出有有效字符串 field 的项
              const validItems = items.filter(it => typeof it?.field === 'string') as Array<{ field: string; order: 'ascend' | 'descend' | null }>
              if (validItems.length === 0) {
                // sorter 中没有有效排序信息 — 不清空现有排序，避免误删
                return
              }
              // 取被操作的列（有非 null order 的优先；如果都是 null 取第一个）
              const activeItem = validItems.find(it => it.order !== null) ?? validItems[0]
              const field = activeItem.field
              const order = activeItem.order
              if (order === null) {
                // 清除：只移除该字段的排序规则，保留其他
                setViewSortings(prev => prev.filter(sr => sr.field_name !== field))
              } else {
                // 设置：替换同字段规则并置顶
                const newSort = { field_name: field, direction: order === 'ascend' ? 'asc' as const : 'desc' as const }
                setViewSortings(prev => {
                  const without = prev.filter(sr => sr.field_name !== field)
                  return [newSort, ...without]
                })
              }
              setOffset(0)
            }}
            onRow={(record) => ({ onDoubleClick: () => { setDetailRow(record); setDetailOpen(true) } })}
          />
        ) : mode === 'kanban' ? (
          <KanbanView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} sortings={viewSortings} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        ) : mode === 'gallery' ? (
          <GalleryView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        ) : (
          <CalendarView rows={rowList.items || []} fields={table?.fields || []} view={activeView} density={settings.density} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        )}
      </div>

      {/* 底部聚合条 */}
      {selectedRowKeys.length > 0 && (
        <div style={{ padding: '8px 16px', borderTop: '1px solid #e5e7eb', background: '#fff', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <Badge color="blue" text={`已选 ${selectedRowKeys.length} 行`} />
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
                onClick={() => Modal.confirm({ title: `确定删除 ${selectedRowKeys.length} 行？`, onOk: () => deleteRows.mutate(selectedRowKeys) })}
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
        <CreateViewForm
          fields={table?.fields || []}
          onCreate={(name, vt, opts) => {
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
          <EditViewForm
            fields={table?.fields || []}
            view={activeView}
            onSave={(name, vt, opts) => {
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

      {/* 权限设置 Modal */}
      <Modal
        title="表权限设置"
        open={permOpen}
        onCancel={() => setPermOpen(false)}
        confirmLoading={savePerm.isPending}
        okText="保存"
        onOk={() => {
          // 将 Modal 内表单的值从 window 上读 — 简化版
          const el = document.querySelector<HTMLInputElement>('input[data-perm-comment]')
          const hiddenInputs = document.querySelectorAll<HTMLInputElement>('input[data-perm-hidden]:checked')
          const hiddenFields = Array.from(hiddenInputs).map(i => i.value)
          savePerm.mutate({
            hidden_fields: hiddenFields,
            row_filters: null,
            comment: el?.value ?? undefined,
          })
        }}
      >
        <PermissionEditor fields={table?.fields || []} data={permData} />
      </Modal>

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
    </div>
  )
}

// ─────────────── 创建视图表单（含 view_options 配置） ───────────────

function CreateViewForm({
  fields,
  onCreate,
}: {
  fields: Field[]
  onCreate: (name: string, viewType: string, viewOptions: Record<string, unknown>) => void
}) {
  const [name, setName] = useState('')
  const [vt, setVt] = useState('grid')
  const [opts, setOpts] = useState<Record<string, unknown>>({})

  // 兼容后端真实 field_type name 和历史别名
  const _isOneOf = (ft: string, ...names: string[]) =>
    names.includes(ft) || names.includes(FIELD_TYPE_ALIASES[ft] ?? ft)

  const selectFields = fields.filter(f => _isOneOf(f.field_type, 'select', 'multiselect'))
  const dateFields = fields.filter(f => _isOneOf(f.field_type, 'date', 'datetime'))
  const textFields = fields.filter(f => _isOneOf(f.field_type, 'text', 'longtext'))
  const numberFields = fields.filter(f => _isOneOf(f.field_type, 'number', 'float', 'percentage', 'timestamp'))
  const imageFields = fields.filter(f => f.field_type === 'attachment')
  const allFields = fields.filter(f => !f.hidden)

  const updateOpt = (key: string, value: unknown) => {
    setOpts(prev => {
      const next = { ...prev }
      if (value === undefined || value === null || value === '') delete next[key]
      else next[key] = value
      return next
    })
  }

  const viewTypeOptions = [
    { value: 'grid', label: '表格（Grid）' },
    { value: 'kanban', label: '看板（Kanban）' },
    { value: 'gallery', label: '画廊（Gallery）' },
    { value: 'calendar', label: '日历（Calendar）' },
  ]

  const kanbanConfig = vt === 'kanban' && (
    <>
      <Form.Item label="分组字段" required tooltip="按哪个字段分组显示为看板列">
        <Select
          value={(opts.group_field as string) || undefined}
          onChange={(v) => updateOpt('group_field', v)}
          placeholder="选择分组字段"
          options={selectFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片标题字段" tooltip="留空使用主键字段">
        <Select
          value={(opts.title_field as string) || undefined}
          onChange={(v) => updateOpt('title_field', v)}
          placeholder="选择标题字段"
          options={textFields.concat(fields.filter(f => f.is_primary)).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片排序字段" tooltip="每列卡片按此字段排序；留空则按 API 返回顺序 + 紧急置顶">
        <Select
          value={(opts.card_sort_field as string) || undefined}
          onChange={(v) => updateOpt('card_sort_field', v)}
          placeholder="选择排序字段（可选）"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片排序方向" tooltip="配合卡片排序字段使用">
        <Select
          value={(opts.card_sort_direction as 'asc' | 'desc') || 'desc'}
          onChange={(v: 'asc' | 'desc') => updateOpt('card_sort_direction', v)}
          style={{ width: '100%' }}
          options={[{ value: 'desc', label: '降序 ↓' }, { value: 'asc', label: '升序 ↑' }]}
        />
      </Form.Item>
      <Form.Item label="逾期/紧急卡片置顶" valuePropName="checked" tooltip="有截止日期时，逾期和临近截止的卡片始终排在列顶">
        <Switch
          checked={opts.pin_urgent !== false}
          onChange={(v) => updateOpt('pin_urgent', v)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      </Form.Item>
      <Form.Item label="进度百分比字段" tooltip="0-100 的数值字段，显示进度条">
        <Select
          value={(opts.progress_field as string) || undefined}
          onChange={(v) => updateOpt('progress_field', v)}
          placeholder="选择进度字段"
          options={numberFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="截止日期字段" tooltip="配置后自动显示逾期/临近提醒">
        <Select
          value={(opts.due_date_field as string) || undefined}
          onChange={(v) => updateOpt('due_date_field', v)}
          placeholder="选择日期字段"
          options={dateFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="优先级字段" tooltip="Select 字段，不同值显示不同颜色徽章">
        <Select
          value={(opts.priority_field as string) || undefined}
          onChange={(v) => updateOpt('priority_field', v)}
          placeholder="选择优先级字段"
          options={selectFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="负责人字段">
        <Select
          value={(opts.assignee_field as string) || undefined}
          onChange={(v) => updateOpt('assignee_field', v)}
          placeholder="选择负责人字段"
          options={textFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片额外字段" tooltip="在卡片底部以标签形式展示">
        <Select
          mode="multiple"
          value={(opts.card_fields as string[]) || []}
          onChange={(v) => updateOpt('card_fields', v)}
          placeholder="选择要显示的字段"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="紧急阈值（天）" tooltip="截止日期前多少天标记为紧急">
        <Select
          value={(opts.urgent_threshold_days as number) || 3}
          onChange={(v) => updateOpt('urgent_threshold_days', v)}
          options={[{ value: 1, label: '1 天' }, { value: 3, label: '3 天' }, { value: 5, label: '5 天' }, { value: 7, label: '7 天' }]}
          style={{ width: '100%' }}
        />
      </Form.Item>
    </>
  )

  const calendarConfig = vt === 'calendar' && (
    <>
      <Form.Item label="日期字段" required tooltip="事件的日期">
        <Select
          value={(opts.start_field as string) || undefined}
          onChange={(v) => updateOpt('start_field', v)}
          placeholder="选择日期/时间字段"
          options={dateFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="事件标题字段" tooltip="日历格中显示的事件文字">
        <Select
          value={(opts.title_field as string) || undefined}
          onChange={(v) => updateOpt('title_field', v)}
          placeholder="留空则自动选第一个文本字段"
          options={textFields.concat(fields.filter(f => f.is_primary)).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="分组/颜色字段" tooltip="Select 字段，不同值渲染不同颜色侧边条">
        <Select
          value={(opts.group_field as string) || undefined}
          onChange={(v) => updateOpt('group_field', v)}
          placeholder="选择分组字段（可选）"
          options={selectFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="默认打开的日历层级">
        <Select
          value={(opts.calendar_mode as string) || 'month'}
          onChange={(v) => updateOpt('calendar_mode', v)}
          style={{ width: '100%' }}
          options={[
            { value: 'year', label: '年视图（12 月概览）' },
            { value: 'month', label: '月视图（标准日历）' },
            { value: 'week', label: '周视图（7 天横向）' },
          ]}
        />
      </Form.Item>
    </>
  )

  const galleryConfig = vt === 'gallery' && (
    <>
      <Form.Item label="标题字段">
        <Select
          value={(opts.title_field as string) || undefined}
          onChange={(v) => updateOpt('title_field', v)}
          placeholder="留空则自动选第一个文本字段"
          options={textFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="副标题字段">
        <Select
          value={(opts.subtitle_field as string) || undefined}
          onChange={(v) => updateOpt('subtitle_field', v)}
          placeholder="卡片标题下方的补充文字"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="标签字段">
        <Select
          value={(opts.tag_field as string) || undefined}
          onChange={(v) => updateOpt('tag_field', v)}
          placeholder="显示为卡片右上角徽章"
          options={selectFields.concat(allFields.filter(f => f.field_type === 'boolean')).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="附加信息字段" tooltip="显示在卡片底部的小标签（可多选）">
        <Select
          mode="multiple"
          value={(opts.meta_fields as string[]) || []}
          onChange={(v) => updateOpt('meta_fields', v.length ? v : undefined)}
          placeholder="选几个字段当卡片脚注"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="图片/附件字段">
        <Select
          value={(opts.image_field as string) || undefined}
          onChange={(v) => updateOpt('image_field', v)}
          placeholder="留空则自动选第一个附件字段"
          options={imageFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
    </>
  )

  return (
    <Form layout="vertical" style={{ marginTop: 12 }}>
      <Form.Item label="视图名称" required>
        <Input placeholder="例如：只看进行中" value={name} onChange={e => setName(e.target.value)} autoFocus />
      </Form.Item>
      <Form.Item label="视图类型">
        <Select value={vt} onChange={(v) => { setVt(v); setOpts({}) }} options={viewTypeOptions} />
      </Form.Item>
      {kanbanConfig}
      {calendarConfig}
      {galleryConfig}
      <div style={{ textAlign: 'right', marginTop: 12 }}>
        <Button type="primary" disabled={!name.trim()}
          onClick={() => onCreate(name.trim(), vt, opts)}>创建</Button>
      </div>
    </Form>
  )
}

/** 编辑视图表单 —— 复用 CreateViewForm 的字段布局，初始值来自现有 View. */
function EditViewForm({
  fields,
  view,
  onSave,
}: {
  fields: Field[]
  view: View
  onSave: (name: string, viewType: string, viewOptions: Record<string, unknown>) => void
}) {
  const [name, setName] = useState(view.name)
  const [vt, setVt] = useState(view.view_type || 'grid')
  const [opts, setOpts] = useState<Record<string, unknown>>({ ...(view.view_options || {}) })

  // 兼容后端真实 field_type name 和历史别名
  const _isOneOf = (ft: string, ...names: string[]) =>
    names.includes(ft) || names.includes(FIELD_TYPE_ALIASES[ft] ?? ft)

  const selectFields = fields.filter(f => _isOneOf(f.field_type, 'select', 'multiselect'))
  const dateFields = fields.filter(f => _isOneOf(f.field_type, 'date', 'datetime'))
  const textFields = fields.filter(f => _isOneOf(f.field_type, 'text', 'longtext'))
  const numberFields = fields.filter(f => _isOneOf(f.field_type, 'number', 'float', 'percentage', 'timestamp'))
  const imageFields = fields.filter(f => f.field_type === 'attachment')
  const allFields = fields.filter(f => !f.hidden)

  const updateOpt = (key: string, value: unknown) => {
    setOpts(prev => {
      const next = { ...prev }
      if (value === undefined || value === null || value === '') delete next[key]
      else next[key] = value
      return next
    })
  }

  const viewTypeOptions = [
    { value: 'grid', label: '表格（Grid）' },
    { value: 'kanban', label: '看板（Kanban）' },
    { value: 'gallery', label: '画廊（Gallery）' },
    { value: 'calendar', label: '日历（Calendar）' },
  ]

  const kanbanConfig = vt === 'kanban' && (
    <>
      <Form.Item label="分组字段" required>
        <Select
          value={(opts.group_field as string) || undefined}
          onChange={(v) => updateOpt('group_field', v)}
          placeholder="选择分组字段"
          options={selectFields.concat(fields.filter(f => f.field_type === 'boolean')).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片标题字段">
        <Select
          value={(opts.title_field as string) || undefined}
          onChange={(v) => updateOpt('title_field', v)}
          placeholder="选择标题字段"
          options={textFields.concat(fields.filter(f => f.is_primary)).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片排序字段" tooltip="每列卡片按此字段排序；留空则按 API 返回顺序 + 紧急置顶">
        <Select
          value={(opts.card_sort_field as string) || undefined}
          onChange={(v) => updateOpt('card_sort_field', v)}
          placeholder="选择排序字段（可选）"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片排序方向" tooltip="配合卡片排序字段使用">
        <Select
          value={(opts.card_sort_direction as 'asc' | 'desc') || 'desc'}
          onChange={(v: 'asc' | 'desc') => updateOpt('card_sort_direction', v)}
          style={{ width: '100%' }}
          options={[{ value: 'desc', label: '降序 ↓' }, { value: 'asc', label: '升序 ↑' }]}
        />
      </Form.Item>
      <Form.Item label="逾期/紧急卡片置顶" valuePropName="checked" tooltip="有截止日期时，逾期和临近截止的卡片始终排在列顶">
        <Switch
          checked={opts.pin_urgent !== false}
          onChange={(v) => updateOpt('pin_urgent', v)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      </Form.Item>
      <Form.Item label="进度百分比字段">
        <Select
          value={(opts.progress_field as string) || undefined}
          onChange={(v) => updateOpt('progress_field', v)}
          placeholder="选择进度字段"
          options={numberFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="截止日期字段">
        <Select
          value={(opts.due_date_field as string) || undefined}
          onChange={(v) => updateOpt('due_date_field', v)}
          placeholder="选择日期字段"
          options={dateFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="优先级字段">
        <Select
          value={(opts.priority_field as string) || undefined}
          onChange={(v) => updateOpt('priority_field', v)}
          placeholder="选择优先级字段"
          options={selectFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="负责人字段">
        <Select
          value={(opts.assignee_field as string) || undefined}
          onChange={(v) => updateOpt('assignee_field', v)}
          placeholder="选择负责人字段"
          options={textFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="卡片额外字段">
        <Select
          mode="multiple"
          value={(opts.card_fields as string[]) || []}
          onChange={(v) => updateOpt('card_fields', v)}
          placeholder="选择要显示的字段"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
    </>
  )

  const calendarConfig = vt === 'calendar' && (
    <>
      <Form.Item label="日期字段" required tooltip="事件的日期">
        <Select
          value={(opts.start_field as string) || undefined}
          onChange={(v) => updateOpt('start_field', v)}
          placeholder="选择日期/时间字段"
          options={dateFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="事件标题字段" tooltip="日历格中显示的事件文字">
        <Select
          value={(opts.title_field as string) || undefined}
          onChange={(v) => updateOpt('title_field', v)}
          placeholder="留空则自动选第一个文本字段"
          options={textFields.concat(fields.filter(f => f.is_primary)).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="分组/颜色字段" tooltip="Select 字段，不同值渲染不同颜色侧边条">
        <Select
          value={(opts.group_field as string) || undefined}
          onChange={(v) => updateOpt('group_field', v)}
          placeholder="选择分组字段（可选）"
          options={selectFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="默认打开的日历层级">
        <Select
          value={(opts.calendar_mode as string) || 'month'}
          onChange={(v) => updateOpt('calendar_mode', v)}
          style={{ width: '100%' }}
          options={[
            { value: 'year', label: '年视图（12 月概览）' },
            { value: 'month', label: '月视图（标准日历）' },
            { value: 'week', label: '周视图（7 天横向）' },
          ]}
        />
      </Form.Item>
    </>
  )

  const galleryConfig = vt === 'gallery' && (
    <>
      <Form.Item label="标题字段">
        <Select
          value={(opts.title_field as string) || undefined}
          onChange={(v) => updateOpt('title_field', v)}
          placeholder="留空则自动选第一个文本字段"
          options={textFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="副标题字段">
        <Select
          value={(opts.subtitle_field as string) || undefined}
          onChange={(v) => updateOpt('subtitle_field', v)}
          placeholder="卡片标题下方的补充文字"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="标签字段">
        <Select
          value={(opts.tag_field as string) || undefined}
          onChange={(v) => updateOpt('tag_field', v)}
          placeholder="显示为卡片右上角徽章"
          options={selectFields.concat(allFields.filter(f => f.field_type === 'boolean')).map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="附加信息字段" tooltip="显示在卡片底部的小标签（可多选）">
        <Select
          mode="multiple"
          value={(opts.meta_fields as string[]) || []}
          onChange={(v) => updateOpt('meta_fields', v.length ? v : undefined)}
          placeholder="选几个字段当卡片脚注"
          options={allFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
      <Form.Item label="图片/附件字段">
        <Select
          value={(opts.image_field as string) || undefined}
          onChange={(v) => updateOpt('image_field', v)}
          placeholder="留空则自动选第一个附件字段"
          options={imageFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
          style={{ width: '100%' }}
          allowClear
        />
      </Form.Item>
    </>
  )

  return (
    <Form layout="vertical" style={{ marginTop: 12 }}>
      <Form.Item label="视图名称" required>
        <Input value={name} onChange={e => setName(e.target.value)} autoFocus />
      </Form.Item>
      <Form.Item label="视图类型">
        <Select value={vt} onChange={(v) => { setVt(v); setOpts({}) }} options={viewTypeOptions} />
      </Form.Item>
      {kanbanConfig}
      {calendarConfig}
      {galleryConfig}
      <div style={{ textAlign: 'right', marginTop: 12 }}>
        <Button type="primary" disabled={!name.trim()}
          onClick={() => onSave(name.trim(), vt, opts)}>保存</Button>
      </div>
    </Form>
  )
}

// ─────────────── 筛选规则可视化编辑器依赖（操作符表） ───────────────

const FIELD_OPS: Record<string, Array<{ op: string; label: string; needValue?: boolean; valueKind?: 'text' | 'number' | 'select' | 'date' | 'boolean' }>> = {
  text: [
    { op: 'contains', label: '包含', valueKind: 'text' },
    { op: 'starts_with', label: '开头为', valueKind: 'text' },
    { op: 'ends_with', label: '结尾为', valueKind: 'text' },
    { op: '=', label: '等于', valueKind: 'text' },
    { op: '!=', label: '不等于', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  number: [
    { op: '=', label: '等于', valueKind: 'number' },
    { op: '!=', label: '不等于', valueKind: 'number' },
    { op: '>', label: '大于', valueKind: 'number' },
    { op: '>=', label: '大于等于', valueKind: 'number' },
    { op: '<', label: '小于', valueKind: 'number' },
    { op: '<=', label: '小于等于', valueKind: 'number' },
    { op: 'in', label: '在列表中（逗号分隔）', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  select: [
    { op: '=', label: '等于', valueKind: 'select' },
    { op: '!=', label: '不等于', valueKind: 'select' },
    { op: 'in', label: '在列表中', valueKind: 'select' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  date: [
    { op: '=', label: '等于', valueKind: 'date' },
    { op: '>', label: '晚于', valueKind: 'date' },
    { op: '>=', label: '不早于', valueKind: 'date' },
    { op: '<', label: '早于', valueKind: 'date' },
    { op: '<=', label: '不晚于', valueKind: 'date' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  boolean: [
    { op: '=', label: '等于', valueKind: 'boolean' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
}

function _opsForField(fieldType: string) {
  if (FIELD_OPS[fieldType]) return FIELD_OPS[fieldType]
  // 后端实际 field_type name → 前端操作符组的别名映射
  if (['longtext', 'email', 'url', 'phone'].includes(fieldType)) return FIELD_OPS.text
  if (['float', 'decimal', 'percentage', 'timestamp'].includes(fieldType)) return FIELD_OPS.number
  if (['multiselect'].includes(fieldType)) return FIELD_OPS.select
  if (['datetime'].includes(fieldType)) return FIELD_OPS.date
  if (fieldType === 'attachment') return FIELD_OPS.text.slice(5)  // 只给空/非空
  if (fieldType === 'link') return [
    { op: 'is_null', label: '未关联', needValue: true },
    { op: 'is_not_null', label: '已关联', needValue: true },
    { op: 'has_any', label: '包含任一目标行（逗号分隔 id）', valueKind: 'text' },
    { op: 'has_all', label: '包含全部目标行（逗号分隔 id）', valueKind: 'text' },
  ]
  return FIELD_OPS.text
}

// ─────────────── 视图配置对话框（可视化筛选 / 排序 / 视图设置） ───────────────

interface FilterRule { field_name: string; op: string; value?: unknown }
interface SortRule { field_name: string; direction: 'asc' | 'desc' }

interface ViewConfigDialogProps {
  open: boolean
  viewType: string
  filters: FilterRule[]
  sortings: SortRule[]
  viewOptions: Record<string, unknown> | null
  fields: Field[]
  onClose: () => void
  filterLogic: 'AND' | 'OR'
  onSaveFilterLogic: (logic: 'AND' | 'OR') => void
  onSaveFilters: (f: FilterRule[]) => void
  onSaveSortings: (s: SortRule[]) => void
  onSaveOptions: (o: Record<string, unknown> | null) => void
}

function ViewConfigDialog({
  open, viewType, filters, sortings, viewOptions, fields, onClose,
  filterLogic, onSaveFilterLogic, onSaveFilters, onSaveSortings, onSaveOptions,
}: ViewConfigDialogProps) {
  const [draftFilters, setDraftFilters] = useState<FilterRule[]>([])
  const [draftSorts, setDraftSorts] = useState<SortRule[]>([])
  const [draftFilterLogic, setDraftFilterLogic] = useState<'AND' | 'OR'>('AND')
  const [draftOpt, setDraftOpt] = useState<Record<string, unknown>>({})
  const [activeTab, setActiveTab] = useState<'filter' | 'sort' | 'view'>('filter')

  useEffect(() => {
    if (open) {
      setDraftFilters(filters.length ? [...filters] : [{ field_name: '', op: 'contains' }])
      setDraftSorts(sortings.length ? [...sortings] : [{ field_name: '', direction: 'asc' }])
      setDraftFilterLogic(filterLogic)
      setDraftOpt((viewOptions || {}) as Record<string, unknown>)
      setActiveTab('filter')
    }
  }, [open, filters, sortings, filterLogic, viewOptions])

  const filterableFields = fields.filter(f => !f.hidden)
  const sortableFields = fields.filter(f => !f.hidden)

  // ── 筛选规则增删改 ──
  const addFilter = () => setDraftFilters(prev => [...prev, { field_name: '', op: 'contains' }])
  const removeFilter = (idx: number) => setDraftFilters(prev => prev.filter((_, i) => i !== idx))
  const updateFilter = (idx: number, patch: Partial<FilterRule>) => {
    setDraftFilters(prev => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  // ── 排序规则增删改 ──
  const addSort = () => setDraftSorts(prev => [...prev, { field_name: '', direction: 'asc' }])
  const removeSort = (idx: number) => setDraftSorts(prev => prev.filter((_, i) => i !== idx))
  const updateSort = (idx: number, patch: Partial<SortRule>) => {
    setDraftSorts(prev => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  // ── 视图专属设置结构化配置（保留原有的丰富字段）──
  type _OptField =
    | { key: string; label: string; fieldTypes: string[]; kind?: 'select' }
    | { key: string; label: string; fieldTypes: 'multiple'; kind: 'multiple' }
    | { key: string; label: string; fieldTypes: 'number'; kind: 'number' }
    | { key: string; label: string; fieldTypes: 'direction'; kind: 'direction' }
    | { key: string; label: string; fieldTypes: 'boolean'; kind: 'switch' }

  const viewOptFields = useMemo<_OptField[]>(() => {
    if (viewType === 'kanban') {
      return [
        { key: 'group_field', label: '分组字段（Select/Boolean）', fieldTypes: ['select', 'multi_select', 'boolean'] },
        { key: 'title_field', label: '卡片标题字段', fieldTypes: ['text', 'long_text', 'is_primary'] },
        { key: 'progress_field', label: '进度百分比字段（Number）', fieldTypes: ['number', 'decimal'] },
        { key: 'due_date_field', label: '截止日期字段（Date）', fieldTypes: ['date', 'datetime'] },
        { key: 'priority_field', label: '优先级字段（Select）', fieldTypes: ['select', 'multi_select'] },
        { key: 'assignee_field', label: '负责人字段', fieldTypes: ['text', 'long_text'] },
        { key: 'card_sort_field', label: '卡片排序字段（可选）', fieldTypes: ['number', 'float', 'decimal', 'date', 'datetime', 'select', 'text'] },
        { key: 'card_sort_direction', label: '卡片排序方向', fieldTypes: 'direction', kind: 'direction' },
        { key: 'pin_urgent', label: '逾期/紧急卡片置顶', fieldTypes: 'boolean', kind: 'switch' },
        { key: 'card_fields', label: '卡片额外字段（多选）', fieldTypes: 'multiple', kind: 'multiple' },
        { key: 'urgent_threshold_days', label: '紧急阈值（天）', fieldTypes: 'number', kind: 'number' },
      ]
    }
    if (viewType === 'calendar') {
      return [
        { key: 'start_field', label: '日期字段', fieldTypes: ['date', 'datetime'] },
        { key: 'title_field', label: '事件标题字段（可选）', fieldTypes: ['text', 'long_text', 'is_primary'] },
        { key: 'group_field', label: '分组/颜色字段（Select，可选）', fieldTypes: ['select', 'multi_select'] },
      ]
    }
    if (viewType === 'gallery') {
      return [
        { key: 'title_field', label: '标题字段', fieldTypes: ['text', 'long_text'] },
        { key: 'image_field', label: '图片字段（可选）', fieldTypes: ['attachment', 'image'] },
      ]
    }
    return []
  }, [viewType])

  const viewTabItems = useMemo(() => {
    const items: Array<{ key: string; label: string; children: React.ReactNode }> = [
      {
        key: 'filter',
        label: `筛选${draftFilters.filter(f => f.field_name).length ? ` (${draftFilters.filter(f => f.field_name).length})` : ''}`,
        children: (
          <div style={{ minHeight: 120 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid #f0f0f0' }}>
              <span style={{ fontSize: 13, color: '#475569' }}>条件组合：</span>
              <Space.Compact size="small">
                <Button
                  type={draftFilterLogic === 'AND' ? 'primary' : 'default'}
                  onClick={() => setDraftFilterLogic('AND')}
                >全部满足（AND）</Button>
                <Button
                  type={draftFilterLogic === 'OR' ? 'primary' : 'default'}
                  onClick={() => setDraftFilterLogic('OR')}
                >任一满足（OR）</Button>
              </Space.Compact>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>
                {draftFilterLogic === 'AND' ? '所有筛选条件同时生效' : '任一筛选条件生效即可'}
              </span>
            </div>
            {draftFilters.length === 0 && (
              <div style={{ textAlign: 'center', color: '#94a3b8', padding: '20px 0', border: '1px dashed #e2e8f0', borderRadius: 6 }}>
                暂无筛选条件
              </div>
            )}
            {draftFilters.map((rule, idx) => {
              const currentField = filterableFields.find(f => f.name === rule.field_name)
              const ops = currentField ? _opsForField(currentField.field_type) : FIELD_OPS.text
              const currentOp = ops.find(o => o.op === rule.op)
              const needValue = !!currentOp?.needValue
              const fieldOpts = filterableFields.map(f => ({ value: f.name, label: f.name }))
              const selectFieldOpts = ((currentField?.config as Record<string, unknown> | undefined)?.options as Array<Record<string, unknown>> | undefined || []).map((o: Record<string, unknown>) =>
                String(o.value ?? o.name ?? ''))
              return (
                <div key={idx} style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: '#9ca3af', width: 24, textAlign: 'center', flexShrink: 0 }}>#{idx + 1}</span>
                  <Select size="small" value={rule.field_name || undefined}
                    onChange={(v) => {
                      const nextField = filterableFields.find(f => f.name === v)
                      const nextOps = nextField ? _opsForField(nextField.field_type) : FIELD_OPS.text
                      updateFilter(idx, { field_name: v, op: nextOps[0].op, value: undefined })
                    }}
                    placeholder="字段" style={{ width: 130 }} options={fieldOpts} />
                  <Select size="small" value={rule.op}
                    onChange={(v) => updateFilter(idx, { op: v, value: undefined })}
                    placeholder="操作符" style={{ width: 130 }} options={ops.map(o => ({ value: o.op, label: o.label }))} />
                  {needValue ? (
                    <span style={{ fontSize: 12, color: '#9ca3af' }}>（无需值）</span>
                  ) : currentOp?.valueKind === 'boolean' ? (
                    <Switch size="small" checked={!!rule.value} onChange={(v) => updateFilter(idx, { value: v })} />
                  ) : currentOp?.valueKind === 'number' ? (
                    <InputNumber size="small" value={rule.value as number | undefined}
                      onChange={(v) => updateFilter(idx, { value: v ?? undefined })} style={{ width: 120 }} placeholder="数值" />
                  ) : currentOp?.valueKind === 'select' ? (
                    <Select size="small" value={rule.value as string | undefined}
                      onChange={(v) => updateFilter(idx, { value: v })} style={{ width: 130 }} allowClear
                      options={selectFieldOpts.map(o => ({ value: o, label: o }))} placeholder="值" />
                  ) : currentOp?.valueKind === 'date' ? (
                    <Input size="small" value={rule.value as string | undefined}
                      onChange={(e) => updateFilter(idx, { value: e.target.value })} style={{ width: 140 }}
                      placeholder="YYYY-MM-DD" />
                  ) : (
                    <Input size="small" value={rule.value as string | undefined}
                      onChange={(e) => updateFilter(idx, { value: e.target.value })} style={{ flex: 1 }} placeholder="值" />
                  )}
                  <Button size="small" type="text" danger disabled={draftFilters.length <= 1} icon={<DeleteOutlined />}
                    onClick={() => removeFilter(idx)} />
                </div>
              )
            })}
            <div style={{ marginTop: 8 }}>
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addFilter}>添加筛选条件</Button>
            </div>
          </div>
        ),
      },
      {
        key: 'sort',
        label: `排序${draftSorts.filter(s => s.field_name).length ? ` (${draftSorts.filter(s => s.field_name).length})` : ''}`,
        children: (
          <div style={{ minHeight: 120 }}>
            {draftSorts.length === 0 && (
              <div style={{ textAlign: 'center', color: '#94a3b8', padding: '20px 0', border: '1px dashed #e2e8f0', borderRadius: 6 }}>
                暂无排序规则
              </div>
            )}
            {draftSorts.map((rule, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: '#9ca3af', width: 24, textAlign: 'center', flexShrink: 0 }}>#{idx + 1}</span>
                <Select size="small" value={rule.field_name || undefined}
                  onChange={(v) => updateSort(idx, { field_name: v })}
                  placeholder="字段" style={{ flex: 1 }}
                  options={sortableFields.map(f => ({ value: f.name, label: f.name }))} />
                <Select size="small" value={rule.direction}
                  onChange={(v: 'asc' | 'desc') => updateSort(idx, { direction: v })}
                  style={{ width: 100 }}
                  options={[{ value: 'asc', label: '升序 ↑' }, { value: 'desc', label: '降序 ↓' }]} />
                <Button size="small" type="text" danger disabled={draftSorts.length <= 1} icon={<DeleteOutlined />}
                  onClick={() => removeSort(idx)} />
              </div>
            ))}
            <div style={{ marginTop: 8 }}>
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addSort}>添加排序</Button>
            </div>
          </div>
        ),
      },
    ]
    if (viewOptFields.length > 0) {
      items.push({
        key: 'view',
        label: `${viewType} 专属设置`,
        children: (
          <div>
            {viewOptFields.map(opt => {
              const ft = opt.fieldTypes
              let fieldOptions: Array<{ label: string; value: string }> = []
              let isMultiple = false
              let isNumber = false
              let isDirection = false
              let isSwitch = false

              if (ft === 'multiple') {
                isMultiple = true
                fieldOptions = sortableFields.map(f => ({ label: f.name, value: f.name }))
              } else if (ft === 'number') {
                isNumber = true
              } else if (ft === 'direction') {
                isDirection = true
              } else if (ft === 'boolean') {
                isSwitch = true
              } else {
                fieldOptions = sortableFields
                  .filter(f => ft.includes(f.field_type) || (ft.includes('is_primary') && f.is_primary))
                  .map(f => ({ label: f.name, value: f.name }))
              }

              const currentValue = draftOpt[opt.key]

              return (
                <div key={opt.key} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: '#475569', marginBottom: 4 }}>{opt.label}</div>
                  {isNumber ? (
                    <Select
                      style={{ width: '100%' }}
                      value={(currentValue as number) || 3}
                      onChange={v => setDraftOpt(prev => ({ ...prev, [opt.key]: v }))}
                      options={[{ value: 1, label: '1 天' }, { value: 3, label: '3 天' }, { value: 5, label: '5 天' }, { value: 7, label: '7 天' }]}
                    />
                  ) : isDirection ? (
                    <Select
                      style={{ width: '100%' }}
                      value={(currentValue as 'asc' | 'desc') || 'desc'}
                      onChange={(v: 'asc' | 'desc') => setDraftOpt(prev => ({ ...prev, [opt.key]: v }))}
                      options={[{ value: 'desc', label: '降序 ↓' }, { value: 'asc', label: '升序 ↑' }]}
                    />
                  ) : isSwitch ? (
                    <Switch
                      checked={currentValue !== false}
                      onChange={v => setDraftOpt(prev => ({ ...prev, [opt.key]: v }))}
                      checkedChildren="开"
                      unCheckedChildren="关"
                    />
                  ) : (
                    <Select
                      mode={isMultiple ? 'multiple' : undefined}
                      style={{ width: '100%' }}
                      allowClear
                      showSearch
                      placeholder={isMultiple ? '选择多个字段' : '选择字段'}
                      options={fieldOptions}
                      value={isMultiple ? (currentValue as string[]) || [] : ((currentValue as string) || undefined)}
                      onChange={v => {
                        if (isMultiple) setDraftOpt(prev => ({ ...prev, [opt.key]: v }))
                        else setDraftOpt(prev => ({ ...prev, [opt.key]: v ?? '' }))
                      }}
                    />
                  )}
                </div>
              )
            })}
          </div>
        ),
      })
    }
    return items
  }, [draftFilters, draftSorts, draftFilterLogic, filterableFields, sortableFields, viewOptFields, draftOpt, viewType])

  return (
    <Modal
      title={viewType === 'grid' ? '视图配置' : `视图配置 — ${viewType} 专属设置`}
      open={open}
      onCancel={onClose}
      width={640}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" onClick={() => {
          const cleanFilters = draftFilters.filter(f => f.field_name)
          onSaveFilterLogic(draftFilterLogic)
          onSaveFilters(cleanFilters)
          const cleanSorts = draftSorts.filter(s => s.field_name)
          onSaveSortings(cleanSorts)
          const cleanOpt = Object.fromEntries(
            Object.entries(draftOpt).filter(([, v]) => v !== '' && v != null && (Array.isArray(v) ? v.length > 0 : true)),
          )
          onSaveOptions(Object.keys(cleanOpt).length ? cleanOpt : null)
          onClose()
        }}>保存</Button>,
      ]}
      destroyOnHidden
    >
      <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} size="small" items={viewTabItems} />
    </Modal>
  )
}

// ─────────────── 字段类型到可用操作符 ───────────────

// ─────────────── 列级筛选 / 视图筛选 共用的 field_type → 操作符组映射 ───────────────
// key 必须匹配后端 FieldType.name 的真实值（见 src/cndb/plugins/tables/field_types/__init__.py）
// 别名映射在 FIELD_TYPE_ALIASES 中处理

const FIELD_OPS_BY_TYPE: Record<string, Array<{ op: string; label: string }>> = {
  text: [
    { op: 'contains', label: '包含' },
    { op: 'starts_with', label: '开头为' },
    { op: 'ends_with', label: '结尾为' },
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  longtext: [
    { op: 'contains', label: '包含' },
    { op: 'starts_with', label: '开头为' },
    { op: 'ends_with', label: '结尾为' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  number: [
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: '>', label: '大于' },
    { op: '>=', label: '大于等于' },
    { op: '<', label: '小于' },
    { op: '<=', label: '小于等于' },
    { op: 'in', label: '在列表中（逗号分隔）' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  // float / percentage / timestamp 都走 number 操作符组（后端 DB 列类型都是 Float/Integer）
  float: [
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: '>', label: '大于' },
    { op: '>=', label: '大于等于' },
    { op: '<', label: '小于' },
    { op: '<=', label: '小于等于' },
    { op: 'in', label: '在列表中（逗号分隔）' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  percentage: [
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: '>', label: '大于' },
    { op: '>=', label: '大于等于' },
    { op: '<', label: '小于' },
    { op: '<=', label: '小于等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  timestamp: [
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: '>', label: '大于' },
    { op: '>=', label: '大于等于' },
    { op: '<', label: '小于' },
    { op: '<=', label: '小于等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  select: [
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: 'in', label: '属于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  multiselect: [
    { op: 'contains', label: '包含值' },
    { op: 'in', label: '属于任一' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  date: [
    { op: '=', label: '等于' },
    { op: '>', label: '晚于' },
    { op: '>=', label: '晚于或等于' },
    { op: '<', label: '早于' },
    { op: '<=', label: '早于或等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  datetime: [
    { op: '=', label: '等于' },
    { op: '>', label: '晚于' },
    { op: '>=', label: '晚于或等于' },
    { op: '<', label: '早于' },
    { op: '<=', label: '早于或等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  boolean: [
    { op: '=', label: '等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  email: [
    { op: 'contains', label: '包含' },
    { op: '=', label: '等于' },
    { op: '!=', label: '不等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  phone: [
    { op: 'contains', label: '包含' },
    { op: '=', label: '等于' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  url: [
    { op: 'contains', label: '包含' },
    { op: 'starts_with', label: '开头为' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  attachment: [
    { op: 'is_empty', label: '无附件' },
    { op: 'is_not_empty', label: '有附件' },
  ],
  link: [
    { op: 'is_empty', label: '未关联' },
    { op: 'is_not_empty', label: '已关联' },
    { op: 'has_any', label: '包含任一目标行（逗号分隔 id）' },
    { op: 'has_all', label: '包含全部目标行（逗号分隔 id）' },
  ],
}

// 旧 field_type name → 新 field_type name 的别名映射（兼容历史数据 / 过渡）
const FIELD_TYPE_ALIASES: Record<string, string> = {
  long_text: 'longtext',
  decimal: 'float',
  multi_select: 'multiselect',
  rich_text: 'longtext',
  link_to_table: 'link',
}

function getOpsForField(fieldType: string): Array<{ op: string; label: string }> {
  const resolved = FIELD_TYPE_ALIASES[fieldType] ?? fieldType
  return FIELD_OPS_BY_TYPE[resolved] || FIELD_OPS_BY_TYPE.text
}

// ─────────────── 列级筛选下拉面板组件 ───────────────

function ColumnFilterDropdown({
  field, currentFilter, onApply, onReset,
}: {
  field: Field
  currentFilter?: { op: string; value: unknown }
  onApply: (op: string, value: unknown) => void
  onReset: () => void
}) {
  const [op, setOp] = useState<string>(currentFilter?.op || (getOpsForField(field.field_type)[0]?.op || '='))
  const [value, setValue] = useState<unknown>(currentFilter?.value ?? '')

  // 当 field 变化（切换到不同列）时重置
  useEffect(() => {
    setOp(currentFilter?.op || (getOpsForField(field.field_type)[0]?.op || '='))
    setValue(currentFilter?.value ?? '')
  }, [field.name]) // eslint-disable-line react-hooks/exhaustive-deps

  // 如果是 is_empty / is_not_empty 操作符，不需要输入值
  const noValue = op === 'is_empty' || op === 'is_not_empty'

  const _numericTypes = new Set(['number', 'float', 'decimal', 'percentage', 'timestamp'])
  const _resolveFt = (ft: string) => FIELD_TYPE_ALIASES[ft] ?? ft
  const isSelect = _resolveFt(field.field_type) === 'select' || _resolveFt(field.field_type) === 'multiselect'
  const options: Array<{ value: string; label: string }> = isSelect
    ? ((field.config as Record<string, unknown> | undefined)?.options as Array<Record<string, unknown>> | undefined || []).map((o: Record<string, unknown>) => ({
      value: String(o.value ?? o.name ?? ''),
      label: String(o.value ?? o.name ?? ''),
    }))
    : []

  return (
    <div style={{ padding: 12, width: 280 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#1f2937' }}>
        筛选「{field.name}」
      </div>
      <div style={{ marginBottom: 8 }}>
        <Select
          value={op}
          onChange={(v) => { setOp(v); setValue('') }}
          style={{ width: '100%' }}
          options={getOpsForField(field.field_type).map(o => ({ value: o.op, label: o.label }))}
          size="small"
        />
      </div>
      {!noValue && (
        <div style={{ marginBottom: 12 }}>
          {isSelect ? (
            <Select
              mode={op === 'in' ? 'multiple' : undefined}
              value={value as string | string[] | undefined}
              onChange={(v) => setValue(v)}
              style={{ width: '100%' }}
              size="small"
              placeholder={op === 'in' ? '选择多个值' : '选择值'}
              options={options}
              allowClear
              showSearch
            />
          ) : _numericTypes.has(_resolveFt(field.field_type)) ? (
            <Input
              type="number"
              value={value as string | number}
              onChange={e => setValue(e.target.value)}
              size="small"
              placeholder="输入数值"
            />
          ) : field.field_type === 'boolean' ? (
            <Select
              value={value as boolean | undefined}
              onChange={(v) => setValue(v)}
              style={{ width: '100%' }}
              size="small"
              placeholder="选择"
              options={[{ value: true, label: '是' }, { value: false, label: '否' }]}
              allowClear
            />
          ) : (
            <Input
              value={value as string}
              onChange={e => setValue(e.target.value)}
              size="small"
              placeholder="输入值"
            />
          )}
        </div>
      )}
      {noValue && (
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
          此条件无需输入值
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onReset}>清除</Button>
        <Button
          size="small"
          type="primary"
          onClick={() => {
            if (noValue) {
              onApply(op, null)
            } else {
              onApply(op, value)
            }
          }}
          disabled={!noValue && (value === '' || value === null || value === undefined)}
        >确定</Button>
      </div>
    </div>
  )
}

// ─────────────── Grid 列构建 ───────────────

function buildColumns(
  fields: Field[],
  wid: number | string | undefined,
  viewSortings: Array<{ field_name: string; direction: 'asc' | 'desc' }>,
  viewFilters: Array<{ field_name: string; op: string; value?: unknown }>,
  onFilterApply: (fieldName: string, op: string, value: unknown) => void,
  onFilterReset: (fieldName: string) => void,
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>,
): ColumnsType<RowResponse> {
  return fields.filter(f => !f.hidden).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map<NonNullable<ColumnsType<RowResponse>>[number]>(f => {
      const sortRule = viewSortings.find(s => s.field_name === f.name)
      // 所有有排序规则的列都受控 sortOrder，保证 AntD 内部状态与 viewSortings 同步
      // 这样任何排序列都能正确经历 ascend→descend→null 循环
      const sortOrder: 'ascend' | 'descend' | null | undefined = sortRule
        ? (sortRule.direction === 'asc' ? 'ascend' : 'descend')
        : undefined
      // 表头图标：任何有排序规则的列都显示箭头（视觉提示）
      const hasSortIndicator = !!sortRule
      const filterRule = viewFilters.find(fr => fr.field_name === f.name)
      const currentFilter = filterRule
        ? { op: filterRule.op, value: filterRule.value }
        : undefined
      return {
        key: String(f.id),
        title: (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span>{f.name}{f.required && <span style={{ color: '#ff4d4f' }}>*</span>}</span>
            {hasSortIndicator && (
              sortRule!.direction === 'asc'
                ? <SortAscendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
                : <SortDescendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
            )}
            {currentFilter && (
              <FilterOutlined style={{ fontSize: 11, color: '#1677ff' }} />
            )}
          </span>
        ),
        dataIndex: f.name,
        ellipsis: true,
        width: 160,
        sorter: true,
        sortOrder,
        filterDropdown: ({ confirm, clearFilters }) => (
          <ColumnFilterDropdown
            field={f}
            currentFilter={currentFilter}
            onApply={(op, value) => { onFilterApply(f.name, op, value); confirm?.() }}
            onReset={() => { onFilterReset(f.name); clearFilters?.(); confirm?.() }}
          />
        ),
        filterIcon: (filtered) => (
          <FilterOutlined style={{ color: filtered || currentFilter ? '#1677ff' : undefined }} />
        ),
        render: (v: unknown, record: RowResponse) => (
          <GridCell
            value={v}
            field={f}
            rowId={record.id}
            wid={wid}
            onSave={onCellSave ? (fieldName, value) => onCellSave(record.id, fieldName, value) : undefined}
          />
        ),
      }
    })
}

// KanbanView 已提取到 ./components/KanbanView.tsx

// ─────────────── Gallery 视图 ───────────────

function extractImageUrl(v: unknown): string | null {
  if (!v) return null
  if (typeof v === 'string') {
    if (v.startsWith('http') || v.startsWith('/')) return v
    return null
  }
  if (Array.isArray(v)) {
    const first = v[0]
    return extractImageUrl(first)
  }
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    return (o.url as string) || (o.value as string) || null
  }
  return null
}

// ─────────────── Gallery 视图（优先使用 view_options.title_field / image_field） ───────────────

function GalleryView({ rows, fields, view, density, onRowClick }: { rows: RowResponse[]; fields: Field[]; view?: View | null; density: Density; onRowClick?: (r: RowResponse) => void }) {
  const opts = view?.view_options ?? {}
  const titleField = (opts.title_field as string)
    || fields.find(f => f.field_type === 'text')?.name
    || fields.find(f => f.is_primary)?.name
  const subtitleField = opts.subtitle_field as string | undefined
  const tagField = opts.tag_field as string | undefined
  const metaFields = (opts.meta_fields as string[] | undefined) ?? []
  const titleCol = titleField || 'id'
  // 找图片/附件字段作为缩略图来源：优先 view_options.image_field，否则第一个 attachment
  const imageFieldOpted = opts.image_field as string | undefined
  const imgField = imageFieldOpted
    ? fields.find(f => f.name === imageFieldOpted)
    : fields.find(f => ['image', 'attachment'].includes(f.field_type))
  const imgCol = imgField?.name

  // 渐变色 fallback 的调色板（按标题首字符 hash 选取，保持同一记录颜色稳定）
  const PALETTE = [
    'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)',
    'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
    'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
    'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)',
    'linear-gradient(135deg, #14b8a6 0%, #3b82f6 100%)',
    'linear-gradient(135deg, #f43f5e 0%, #f59e0b 100%)',
    'linear-gradient(135deg, #6366f1 0%, #22d3ee 100%)',
    'linear-gradient(135deg, #84cc16 0%, #10b981 100%)',
  ]
  const pickGradient = (key: string) => {
    let h = 0
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) & 0x7fffffff
    return PALETTE[h % PALETTE.length]
  }

  // 根据 density 调整画廊卡片间距
  const gutter: [number, number] = density === 'compact' ? [8, 8] : density === 'spacious' ? [20, 20] : [16, 16]
  const radius = density === 'compact' ? 6 : density === 'spacious' ? 10 : 8
  const textPadding = density === 'compact' ? 8 : density === 'spacious' ? 16 : 12
  const textFontSize = density === 'compact' ? 13 : density === 'spacious' ? 15 : 14
  const textSubFontSize = density === 'compact' ? 11 : density === 'spacious' ? 13 : 12
  const imgHeight = density === 'compact' ? 110 : density === 'spacious' ? 170 : 140
  const fallbackHeight = density === 'compact' ? 60 : density === 'spacious' ? 100 : 80
  const fallbackFontSize = density === 'compact' ? 16 : density === 'spacious' ? 24 : 20

  return (
    <Row gutter={gutter}>
      {rows.map(r => {
        const imgUrl = imgCol ? extractImageUrl(r[imgCol]) : null
        const titleVal = String(r[titleCol] ?? r.id)
        const subtitleVal = subtitleField ? r[subtitleField] : null
        const tagVal = tagField ? r[tagField] : null
        const gradient = pickGradient(titleVal)
        return (
          <Col xs={24} sm={12} md={8} lg={6} key={r.id}>
            <div
              onClick={() => onRowClick?.(r)}
              style={{ padding: 0, border: '1px solid #e5e7eb', borderRadius: radius, background: '#fff', cursor: 'pointer', overflow: 'hidden', transition: 'box-shadow 0.15s' }}
            >
              {imgUrl ? (
                <div style={{ width: '100%', height: imgHeight, background: '#f5f7fa', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
                  <img
                    src={imgUrl}
                    alt=""
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                  {tagVal != null && tagVal !== '' && (
                    <span style={{ position: 'absolute', top: 6, right: 6, background: 'rgba(0,0,0,0.55)', color: '#fff', fontSize: textSubFontSize, padding: '1px 8px', borderRadius: 10, backdropFilter: 'blur(4px)' }}>{String(tagVal)}</span>
                  )}
                </div>
              ) : (
                <div style={{ width: '100%', height: fallbackHeight, background: gradient, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 600, fontSize: fallbackFontSize, position: 'relative' }}>
                  {titleVal.slice(0, 2).toUpperCase()}
                  {tagVal != null && tagVal !== '' && (
                    <span style={{ position: 'absolute', top: 6, right: 6, background: 'rgba(255,255,255,0.25)', color: '#fff', fontSize: textSubFontSize, padding: '1px 8px', borderRadius: 10, fontWeight: 500 }}>{String(tagVal)}</span>
                  )}
                </div>
              )}
              <div style={{ padding: textPadding }}>
                <div style={{ fontWeight: 600, marginBottom: 2, fontSize: textFontSize, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{titleVal}</div>
                {subtitleVal != null && subtitleVal !== '' && (
                  <div style={{ fontSize: textSubFontSize, color: '#6b7280', marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(subtitleVal)}</div>
                )}
                {metaFields.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {metaFields.map(mf => {
                      const v = r[mf]
                      if (v == null || v === '') return null
                      return (
                        <span key={mf} style={{ fontSize: textSubFontSize - 1, color: '#6b7280', background: '#f3f4f6', padding: '1px 6px', borderRadius: 3 }}>{String(v)}</span>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </Col>
        )
      })}
      {rows.length === 0 && <Empty description="暂无记录" style={{ padding: 48 }} />}
    </Row>
  )
}

// CalendarView 已提取到 ./components/CalendarView.tsx（支持年/月/周万年历模式）

// ─────────────── 权限编辑器（内嵌在 Modal 内） ───────────────

function PermissionEditor({ fields, data }: { fields: Field[]; data?: TablePermission }) {
  const [comment, setComment] = useState(data?.comment || '')
  const hiddenSet = new Set(data?.hidden_fields || [])

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>隐藏字段（勾选后用户不可见）</div>
      <Form>
        {fields.filter(f => !f.hidden).map(f => (
          <Form.Item key={f.id} style={{ marginBottom: 4 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <input
                type="checkbox"
                value={f.name}
                defaultChecked={hiddenSet.has(f.name)}
                data-perm-hidden
              />
              {f.name} <span style={{ color: '#9ca3af', fontSize: 11 }}>({f.field_type})</span>
            </label>
          </Form.Item>
        ))}
      </Form>
      <div style={{ marginTop: 16, fontSize: 13, fontWeight: 600, marginBottom: 8 }}>备注</div>
      <Input.TextArea
        rows={3}
        placeholder="权限备注"
        value={comment}
        onChange={e => setComment(e.target.value)}
        data-perm-comment
      />
    </div>
  )
}

// ─────────────── 移动表单（内嵌在 Modal 内） ───────────────

function MoveTableForm({ currentWid }: { currentWid: number | string }) {
  const { data: workspaces = [], isLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => import('@/api').then(m => m.workspaceApi.list()),
  })
  const options = workspaces.filter(w => String(w.id) !== String(currentWid))
  return (
    <div style={{ marginTop: 12 }}>
      {isLoading ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>加载中...</div>
      ) : options.length === 0 ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>没有其他工作区可移动</div>
      ) : (
        <Select
          style={{ width: '100%' }}
          placeholder="选择目标工作区"
          options={options.map(w => ({ value: w.id, label: w.name }))}
          data-move-ws
        />
      )}
    </div>
  )
}

// ─────────────── 显示模式 Dialog（全局用户设置） ───────────────

interface TableSettingsDialogProps {
  open: boolean
  onClose: () => void
  onAfterSave?: () => void
}

function TableSettingsDialog({ open, onClose, onAfterSave }: TableSettingsDialogProps) {
  const { settings, updateSettings, resetSettings } = useTableSettings()
  const [draft, setDraft] = useState(settings)

  useEffect(() => {
    if (open) setDraft(settings)
  }, [open, settings])

  const updateDraft = <K extends keyof typeof draft>(key: K, value: typeof draft[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  const handleOk = () => {
    updateSettings(draft)
    onAfterSave?.()
    message.success('设置已保存（适用于所有数据表）')
    onClose()
  }

  const handleReset = () => {
    resetSettings()
    setDraft({ ...DEFAULT_TABLE_SETTINGS })
    message.info('已重置为默认值')
  }

  return (
    <Modal
      title="显示模式"
      open={open}
      onCancel={onClose}
      width={400}
      okText="保存"
      cancelText="取消"
      onOk={handleOk}
      destroyOnHidden
      className="table-settings-dialog"
      footer={[
        <Button key="reset" size="small" onClick={handleReset}>重置默认</Button>,
        <Button key="cancel" size="small" onClick={onClose}>取消</Button>,
        <Button key="ok" size="small" type="primary" onClick={handleOk}>保存</Button>,
      ]}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* 内容间距 — 横向 radiogroup 样式 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: '#374151', whiteSpace: 'nowrap', minWidth: 56 }}>间距</span>
          <Select
            size="small"
            value={draft.density}
            onChange={(v: typeof draft.density) => updateDraft('density', v)}
            style={{ flex: 1 }}
            options={[
              { value: 'compact', label: '紧凑' },
              { value: 'comfortable', label: '适中' },
              { value: 'spacious', label: '宽松' },
            ]}
          />
        </div>

        {/* 每页行数 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: '#374151', whiteSpace: 'nowrap', minWidth: 56 }}>每页</span>
          <Select
            size="small"
            value={draft.defaultPageSize}
            onChange={(v: number) => updateDraft('defaultPageSize', v)}
            style={{ flex: 1 }}
            options={[
              { value: 25, label: '25 条' },
              { value: 50, label: '50 条' },
              { value: 100, label: '100 条' },
              { value: 200, label: '200 条' },
            ]}
          />
        </div>

        {/* 显示选项 — 三开关横排 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, paddingTop: 4, borderTop: '1px solid #f0f0f0' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <Switch size="small" checked={draft.bordered} onChange={(v) => updateDraft('bordered', v)} />
            <span>边框</span>
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <Switch size="small" checked={draft.showHeader} onChange={(v) => updateDraft('showHeader', v)} />
            <span>表头</span>
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <Switch size="small" checked={draft.striped} onChange={(v) => updateDraft('striped', v)} />
            <span>斑马纹</span>
          </label>
        </div>
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: '#9ca3af', textAlign: 'center' }}>
        保存到浏览器，对所有视图生效
      </div>
    </Modal>
  )
}

// ─────────────── 一些保留但暂隐藏的图标引用（让打包器知道没丢依赖） ───────────────

void DownOutlined; void CloseOutlined; void Switch


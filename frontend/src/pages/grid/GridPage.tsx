/** Grid 主应用 — 集成视图 Tab / 三种视图 / inline 编辑 / 导入导出 / 行复制. */

import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Table, Button, Space, Tag, Modal, Typography, message, Tooltip, Dropdown, Empty, Row, Col, Badge, Input, InputNumber, Tabs, Select, Form, Switch } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, ColumnHeightOutlined,
  FilterOutlined, MoreOutlined, ArrowLeftOutlined, EyeOutlined, SettingOutlined,
  AppstoreOutlined, CopyOutlined, ImportOutlined, DownOutlined, CloseOutlined,
  SaveOutlined, CalendarOutlined, ShareAltOutlined, SafetyOutlined, SwapOutlined,
  SearchOutlined, SortAscendingOutlined, SortDescendingOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi, viewApi, permissionApi } from '@/api'
import type { RowResponse, Field, TableDetail, View, ViewCreate, TablePermission } from '@/api'
import GridCell from './components/GridCell'
import RowDetailDrawer from './components/RowDetailDrawer'
import KanbanView from './components/KanbanView'
import { useResponsive } from '@/hooks/useResponsive'
import { useTableSettings } from '@/theme/TableSettingsProvider'
import { densityToSize, DEFAULT_TABLE_SETTINGS } from '@/theme/tableSettings'

// Modal 组件 lazy import：点击打开时才加载
const FieldManager = lazy(() => import('@/pages/modals/FieldManager'))
const ImportExportDialog = lazy(() => import('@/pages/modals/ImportExportDialog'))

function ModalFallback() {
  return null
}

const { Text } = Typography
type ViewMode = 'grid' | 'kanban' | 'gallery' | 'calendar'

export default function GridPage() {
  const { wid, tid } = useParams<{ wid: string; tid: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { isMobile } = useResponsive()
  const { settings } = useTableSettings()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [mode, setMode] = useState<ViewMode>('grid')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRow, setDetailRow] = useState<RowResponse | null>(null)
  const [fieldMgrOpen, setFieldMgrOpen] = useState(false)
  const [importExportOpen, setImportExportOpen] = useState(false)
  const [viewConfigOpen, setViewConfigOpen] = useState(false)
  const [createViewOpen, setCreateViewOpen] = useState(false)
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
  // 表头排序：单个字段排序 {field_name: direction} 或 null
  const [columnSort, setColumnSort] = useState<{ field_name: string; direction: 'asc' | 'desc' } | null>(null)
  // 表头列级筛选：{field_name: { op, value }} 的字典
  const [columnLevelFilters, setColumnLevelFilters] = useState<Record<string, { op: string; value: unknown }>>({})
  const tableKey = `${wid}/${tid}`

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
    if (v) {
      setActiveViewId(v.id)
      setViewFilters(normalizeFilters(v.filters))
      setViewSortings(Array.isArray((v as unknown as Record<string, unknown>).sortings)
        ? (v as unknown as Record<string, unknown>).sortings as Array<{ field_name: string; direction: 'asc' | 'desc' }>
        : Array.isArray((v as unknown as Record<string, unknown>).sorts)
          ? (v as unknown as Record<string, unknown>).sorts as Array<{ field_name: string; direction: 'asc' | 'desc' }>
          : [])
      setViewFilterLogic((((v as unknown as Record<string, unknown>).filter_logic ?? (v as unknown as Record<string, unknown>).filter_type) as 'AND' | 'OR') || 'AND')
      setViewOptionsDraft(v.view_options ?? null)
      // 切换视图时重置列级排序和筛选（视图已有自己的 filters）
      setColumnSort(null)
      setColumnLevelFilters({})
      if (v.view_type === 'kanban') setMode('kanban')
      else if (v.view_type === 'gallery') setMode('gallery')
      else if (v.view_type === 'calendar') setMode('calendar')
      else setMode('grid')
      if (updateUrl) {
        const params = new URLSearchParams(searchParams)
        params.set('view', String(v.id))
        setSearchParams(params, { replace: true })
      }
    } else {
      setActiveViewId(null)
      setViewFilters([])
      setViewSortings([])
      setViewFilterLogic('AND')
      setViewOptionsDraft(null)
      setColumnSort(null)
      setColumnLevelFilters({})
      setMode('grid')
      if (updateUrl && searchParams.has('view')) {
        const params = new URLSearchParams(searchParams)
        params.delete('view')
        setSearchParams(params, { replace: true })
      }
    }
    setOffset(0)
  }

  // 当前激活的视图对象（含 view_options）
  const activeView = activeViewId != null ? views.find(v => String(v.id) === String(activeViewId)) : null

  // URL 深链：?view=<id> 自动选中视图
  useEffect(() => {
    if (!views.length || activeViewId !== null) return
    const vid = searchParams.get('view')
    if (vid) {
      const target = views.find(v => String(v.id) === vid)
      if (target) { loadView(target, false); return }
    }
    // 默认选中 default 或第一个
    const def = views.find(v => v.default) || views[0]
    if (def) loadView(def, false)
    else setActiveViewId(null)
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

  // 合并视图 filters + 表头列级筛选 + 全局关键词 → 后端统一解析
  const effectiveFilters = useMemo(() => {
    const list: Array<Record<string, unknown>> = [...viewFilters]
    for (const [fieldName, flt] of Object.entries(columnLevelFilters)) {
      if (flt.value !== undefined && flt.value !== null && flt.value !== '') {
        list.push({ field_name: fieldName, op: flt.op, value: flt.value })
      }
    }
    if (searchQuery.trim()) list.push({ field_name: '__query__', op: 'contains', value: searchQuery.trim() })
    return list.length ? list : undefined
  }, [viewFilters, columnLevelFilters, searchQuery])

  // 后端 sorts 格式（视图排序 + 表头列排序）
  const sortsParam = useMemo(() => {
    const result = [...viewSortings]
    if (columnSort) result.push({ field_name: columnSort.field_name, direction: columnSort.direction })
    return result.length ? result : undefined
  }, [viewSortings, columnSort])

  const { data: rowList = { items: [], total: 0, offset: 0, limit: 0 } } = useQuery({
    queryKey: ['table-records', tableKey, offset, limit, effectiveFilters, sortsParam, viewFilterLogic],
    queryFn: () => {
      return recordApi.list(wid!, tid!, { offset, limit, filters: effectiveFilters, sorts: sortsParam, filter_logic: viewFilterLogic })
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
  const updateView = useMutation({
    mutationFn: (args: {
      vid: number | string
      filters?: Array<{ field_name: string; op: string; value?: unknown }> | null
      sorts?: Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
      filter_logic?: 'AND' | 'OR'
      view_type?: string
      view_options?: Record<string, unknown> | null
    }) =>
      viewApi.update(wid!, tid!, args.vid, {
        filters: args.filters ?? undefined,
        sorts: args.sorts ?? undefined,
        filter_logic: args.filter_logic ?? undefined,
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

  if (!wid || !tid) return <Empty description="无效的表 ID" style={{ padding: 48 }} />

  const columns = buildColumns(table?.fields || [], wid, columnSort, columnLevelFilters,
    (fieldName, op, value) => {
      setColumnLevelFilters(prev => ({ ...prev, [fieldName]: { op, value } }))
      setOffset(0)
    },
    (fieldName) => {
      setColumnLevelFilters(prev => {
        const next = { ...prev }
        delete next[fieldName]
        return next
      })
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

  // 视图 Tab 项（全部 + 各自定义视图）
  const viewTabItems: Array<{ key: string; label: React.ReactNode; closable?: boolean }> = [
    { key: 'all', label: <span>全部</span> },
    ...views.map(v => ({
      key: String(v.id),
      label: (
        <span>
          {v.name}
          {v.default && <Tag color="blue" style={{ marginLeft: 4 }}>默认</Tag>}
        </span>
      ),
      closable: true,
    })),
  ]

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
          <Dropdown menu={{ items: [
            { key: 'refresh', icon: <ReloadOutlined />, label: '刷新', onClick: () => queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] }) },
            { key: 'perm', icon: <SafetyOutlined />, label: '权限设置', onClick: () => { refetchPerm(); setPermOpen(true) } },
            { key: 'share', icon: <ShareAltOutlined />, label: '分享视图', onClick: () => shareView.mutate() },
            { key: 'revoke', icon: <CloseOutlined />, label: '撤销分享', onClick: () => revokeShare.mutate() },
            { type: 'divider' },
            { key: 'copy', icon: <CopyOutlined />, label: '复制表', onClick: () => tableApi.copy(wid!, tid!).then(() => message.success('表已复制')).then(() => queryClient.invalidateQueries({ queryKey: ['table', tableKey] })) },
            { key: 'move', icon: <SwapOutlined />, label: '移动到其他工作区', onClick: () => setMoveOpen(true) },
            { type: 'divider' },
            { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除表', disabled: true },
          ] }}><Button icon={<MoreOutlined />} /></Dropdown>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => quickAdd.mutate()}>新增行</Button>
        </Space>
      </div>

      {/* 视图 Tab + 视图切换 */}
      <div style={{ padding: '0 16px', background: '#fff', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center' }}>
        <Tabs
          activeKey={activeViewId ? String(activeViewId) : 'all'}
          onChange={(k) => loadView(k === 'all' ? null : views.find(v => String(v.id) === k) || null)}
          onEdit={(targetKey, action) => {
            if (action === 'remove' && typeof targetKey === 'string') {
              removeView.mutate(targetKey)
            }
          }}
          items={viewTabItems.map(item => ({
            key: item.key,
            label: item.label,
            closable: item.closable,
          }))}
          style={{ flex: 1 }}
        />
        <Button
          size="small"
          type="text"
          icon={<PlusOutlined />}
          onClick={() => setCreateViewOpen(true)}
        >新建视图</Button>
        <Space.Compact style={{ marginLeft: 8 }}>
          <Button size="small" type={mode === 'grid' ? 'primary' : 'default'} icon={<ColumnHeightOutlined />} onClick={() => setMode('grid')}>{!isMobile && '表格'}</Button>
          <Button size="small" type={mode === 'kanban' ? 'primary' : 'default'} icon={<AppstoreOutlined />} onClick={() => setMode('kanban')}>{!isMobile && '看板'}</Button>
          <Button size="small" type={mode === 'gallery' ? 'primary' : 'default'} icon={<EyeOutlined />} onClick={() => setMode('gallery')}>{!isMobile && '画廊'}</Button>
          <Button size="small" type={mode === 'calendar' ? 'primary' : 'default'} icon={<CalendarOutlined />} onClick={() => setMode('calendar')}>{!isMobile && '日历'}</Button>
        </Space.Compact>
        <Input.Search
          size="small"
          placeholder="搜索所有文本字段..."
          allowClear
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={e => { setSearchQuery(e.target.value); setOffset(0) }}
          style={{ width: 220, marginLeft: 8 }}
        />
        <Tooltip title="当前视图筛选规则">
          <Button
            size="small"
            icon={<FilterOutlined />}
            type={viewFilters ? 'primary' : 'default'}
            style={{ marginLeft: 8 }}
            onClick={() => setViewConfigOpen(true)}
          />
        </Tooltip>
        <Tooltip title="表格显示设置（对所有数据表生效）">
          <Button
            size="small"
            icon={<ColumnHeightOutlined />}
            style={{ marginLeft: 8 }}
            onClick={() => setSettingsOpen(true)}
          />
        </Tooltip>
        {activeViewId && (
          <Tooltip title="保存筛选规则与视图配置到当前视图">
            <Button
              size="small"
              icon={<SaveOutlined />}
              loading={updateView.isPending}
              onClick={() => updateView.mutate({
                vid: activeViewId,
                filters: viewFilters.length ? viewFilters : null,
                sorts: viewSortings.length ? viewSortings : null,
                filter_logic: viewFilterLogic,
                view_options: viewOptionsDraft,
              })}
            >保存视图</Button>
          </Tooltip>
        )}
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
              type SorterInfo = { field?: string | number | readonly (string | number)[]; order?: 'ascend' | 'descend' | null }
              const s = sorter as SorterInfo | SorterInfo[]
              if (Array.isArray(s)) {
                const first = s[0]
                if (first.order && typeof first.field === 'string') {
                  setColumnSort({ field_name: first.field, direction: first.order === 'ascend' ? 'asc' : 'desc' })
                } else {
                  setColumnSort(null)
                }
              } else if (s.order && typeof s.field === 'string') {
                setColumnSort({ field_name: s.field, direction: s.order === 'ascend' ? 'asc' : 'desc' })
              } else {
                setColumnSort(null)
              }
              setOffset(0)
            }}
            onRow={(record) => ({ onDoubleClick: () => { setDetailRow(record); setDetailOpen(true) } })}
          />
        ) : mode === 'kanban' ? (
          <KanbanView rows={rowList.items || []} fields={table?.fields || []} view={activeView} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        ) : mode === 'gallery' ? (
          <GalleryView rows={rowList.items || []} fields={table?.fields || []} view={activeView} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
        ) : (
          <CalendarView rows={rowList.items || []} fields={table?.fields || []} view={activeView} onRowClick={(r) => { setDetailRow(r); setDetailOpen(true) }} />
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

  const selectFields = fields.filter(f => f.field_type === 'select' || f.field_type === 'multi_select')
  const dateFields = fields.filter(f => f.field_type === 'date' || f.field_type === 'datetime')
  const textFields = fields.filter(f => f.field_type === 'text' || f.field_type === 'long_text')
  const numberFields = fields.filter(f => f.field_type === 'number' || f.field_type === 'decimal')
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
    <Form.Item label="起始时间字段" required tooltip="后端日历视图必须配置 start_field">
      <Select
        value={(opts.start_field as string) || undefined}
        onChange={(v) => updateOpt('start_field', v)}
        placeholder="选择日期/时间字段"
        options={dateFields.map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))}
        style={{ width: '100%' }}
        allowClear
      />
    </Form.Item>
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
  if (['long_text', 'email', 'url', 'phone'].includes(fieldType)) return FIELD_OPS.text
  if (['decimal'].includes(fieldType)) return FIELD_OPS.number
  if (['multi_select'].includes(fieldType)) return FIELD_OPS.select
  if (['datetime'].includes(fieldType)) return FIELD_OPS.date
  if (fieldType === 'attachment') return FIELD_OPS.text.slice(5)  // 只给空/非空
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

  const viewOptFields = useMemo<_OptField[]>(() => {
    if (viewType === 'kanban') {
      return [
        { key: 'group_field', label: '分组字段（Select）', fieldTypes: ['select', 'multi_select'] },
        { key: 'title_field', label: '卡片标题字段', fieldTypes: ['text', 'long_text', 'is_primary'] },
        { key: 'progress_field', label: '进度百分比字段（Number）', fieldTypes: ['number', 'decimal'] },
        { key: 'due_date_field', label: '截止日期字段（Date）', fieldTypes: ['date', 'datetime'] },
        { key: 'priority_field', label: '优先级字段（Select）', fieldTypes: ['select', 'multi_select'] },
        { key: 'assignee_field', label: '负责人字段', fieldTypes: ['text', 'long_text'] },
        { key: 'card_fields', label: '卡片额外字段（多选）', fieldTypes: 'multiple', kind: 'multiple' },
        { key: 'urgent_threshold_days', label: '紧急阈值（天）', fieldTypes: 'number', kind: 'number' },
      ]
    }
    if (viewType === 'calendar') {
      return [
        { key: 'start_field', label: '起始日期字段', fieldTypes: ['date', 'datetime'] },
        { key: 'end_field', label: '结束日期字段（可选）', fieldTypes: ['date', 'datetime'] },
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
              <Button.Group size="small">
                <Button
                  type={draftFilterLogic === 'AND' ? 'primary' : 'default'}
                  onClick={() => setDraftFilterLogic('AND')}
                >全部满足（AND）</Button>
                <Button
                  type={draftFilterLogic === 'OR' ? 'primary' : 'default'}
                  onClick={() => setDraftFilterLogic('OR')}
                >任一满足（OR）</Button>
              </Button.Group>
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

              if (ft === 'multiple') {
                isMultiple = true
                fieldOptions = sortableFields.map(f => ({ label: f.name, value: f.name }))
              } else if (ft === 'number') {
                isNumber = true
              } else {
                fieldOptions = sortableFields
                  .filter(f => ft.includes(f.field_type) || (ft.includes('is_primary') && f.is_primary))
                  .map(f => ({ label: f.name, value: f.name }))
              }

              return (
                <div key={opt.key} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: '#475569', marginBottom: 4 }}>{opt.label}</div>
                  {isNumber ? (
                    <Select
                      style={{ width: '100%' }}
                      value={(draftOpt[opt.key] as number) || 3}
                      onChange={v => setDraftOpt(prev => ({ ...prev, [opt.key]: v }))}
                      options={[{ value: 1, label: '1 天' }, { value: 3, label: '3 天' }, { value: 5, label: '5 天' }, { value: 7, label: '7 天' }]}
                    />
                  ) : (
                    <Select
                      mode={isMultiple ? 'multiple' : undefined}
                      style={{ width: '100%' }}
                      allowClear
                      showSearch
                      placeholder={isMultiple ? '选择多个字段' : '选择字段'}
                      options={fieldOptions}
                      value={isMultiple ? (draftOpt[opt.key] as string[]) || [] : ((draftOpt[opt.key] as string) || undefined)}
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
  }, [draftFilters, draftSorts, filterableFields, sortableFields, viewOptFields, draftOpt, viewType])

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
  long_text: [
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
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  decimal: [
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
  multi_select: [
    { op: 'contains', label: '包含值' },
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
  rich_text: [
    { op: 'contains', label: '包含' },
    { op: 'is_empty', label: '为空' },
    { op: 'is_not_empty', label: '不为空' },
  ],
  link_to_table: [
    { op: 'is_empty', label: '未关联' },
    { op: 'is_not_empty', label: '已关联' },
  ],
}

function getOpsForField(fieldType: string): Array<{ op: string; label: string }> {
  return FIELD_OPS_BY_TYPE[fieldType] || FIELD_OPS_BY_TYPE.text
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

  const isSelect = field.field_type === 'select' || field.field_type === 'multi_select'
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
          ) : field.field_type === 'number' || field.field_type === 'decimal' ? (
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
  columnSort: { field_name: string; direction: 'asc' | 'desc' } | null,
  columnLevelFilters: Record<string, { op: string; value: unknown }>,
  onFilterApply: (fieldName: string, op: string, value: unknown) => void,
  onFilterReset: (fieldName: string) => void,
  onCellSave?: (rowId: number | string, fieldName: string, value: unknown) => Promise<unknown>,
): ColumnsType<RowResponse> {
  return fields.filter(f => !f.hidden).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map<NonNullable<ColumnsType<RowResponse>>[number]>(f => {
      const currentSort = columnSort?.field_name === f.name
        ? (columnSort.direction === 'asc' ? 'ascend' : 'descend') as 'ascend' | 'descend'
        : null
      const hasFilter = !!columnLevelFilters[f.name]
      return {
        key: String(f.id),
        title: (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span>{f.name}{f.required && <span style={{ color: '#ff4d4f' }}>*</span>}</span>
            {currentSort && (
              currentSort === 'ascend'
                ? <SortAscendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
                : <SortDescendingOutlined style={{ fontSize: 12, color: '#1677ff' }} />
            )}
            {hasFilter && (
              <FilterOutlined style={{ fontSize: 11, color: '#1677ff' }} />
            )}
          </span>
        ),
        dataIndex: f.name,
        ellipsis: true,
        width: 160,
        sorter: true,
        sortOrder: currentSort,
        filterDropdown: ({ confirm, clearFilters }) => (
          <ColumnFilterDropdown
            field={f}
            currentFilter={columnLevelFilters[f.name]}
            onApply={(op, value) => { onFilterApply(f.name, op, value); confirm?.() }}
            onReset={() => { onFilterReset(f.name); clearFilters?.(); confirm?.() }}
          />
        ),
        filterIcon: (filtered) => (
          <FilterOutlined style={{ color: filtered || hasFilter ? '#1677ff' : undefined }} />
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

function GalleryView({ rows, fields, view, onRowClick }: { rows: RowResponse[]; fields: Field[]; view?: View | null; onRowClick?: (r: RowResponse) => void }) {
  const titleField = (view?.view_options?.title_field as string)
    || fields.find(f => f.field_type === 'text')?.name
    || fields.find(f => f.is_primary)?.name
  const titleCol = titleField || 'id'
  // 找图片/附件字段作为缩略图来源：优先 view_options.image_field，否则第一个 attachment
  const imageFieldOpted = view?.view_options?.image_field as string | undefined
  const imgField = imageFieldOpted
    ? fields.find(f => f.name === imageFieldOpted)
    : fields.find(f => ['image', 'attachment'].includes(f.field_type))
  const imgCol = imgField?.name

  return (
    <Row gutter={[16, 16]}>
      {rows.map(r => {
        const imgUrl = imgCol ? extractImageUrl(r[imgCol]) : null
        return (
          <Col xs={24} sm={12} md={8} lg={6} key={r.id}>
            <div
              onClick={() => onRowClick?.(r)}
              style={{ padding: 0, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', cursor: 'pointer', overflow: 'hidden' }}
            >
              {imgUrl ? (
                <div style={{ width: '100%', height: 140, background: '#f5f7fa', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                  <img
                    src={imgUrl}
                    alt=""
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                </div>
              ) : (
                <div style={{ width: '100%', height: 80, background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 600, fontSize: 20 }}>
                  {String(r[titleCol] ?? r.id).slice(0, 2).toUpperCase()}
                </div>
              )}
              <div style={{ padding: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 14 }}>{String(r[titleCol] ?? r.id)}</div>
                <div style={{ fontSize: 12, color: '#9ca3af' }}>ID: {r.id}</div>
              </div>
            </div>
          </Col>
        )
      })}
      {rows.length === 0 && <Empty description="暂无记录" style={{ padding: 48 }} />}
    </Row>
  )
}

// ─────────────── Calendar 视图（优先使用 view_options.start_field） ───────────────

function CalendarView({ rows, fields, view, onRowClick }: { rows: RowResponse[]; fields: Field[]; view?: View | null; onRowClick?: (r: RowResponse) => void }) {
  // 起始日期字段：优先 view_options.start_field，否则第一个 date/datetime 字段
  const startFieldOpted = view?.view_options?.start_field as string | undefined
  const dateField = startFieldOpted
    ? fields.find(f => f.name === startFieldOpted)
    : fields.find(f => ['date', 'datetime'].includes(f.field_type))
  const titleField = fields.find(f => f.field_type === 'text')?.name
    || fields.find(f => f.is_primary)?.name || 'id'
  const dateCol = dateField?.name
  const titleCol = titleField

  // 按日期分组
  const groups = new Map<string, RowResponse[]>()
  if (dateCol) {
    for (const r of rows) {
      const raw = r[dateCol]
      const key = raw ? String(raw).slice(0, 10) : '无日期'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(r)
    }
  } else {
    groups.set('全部', rows)
  }

  const sortedKeys = [...groups.keys()].sort((a, b) => {
    if (a === '无日期') return 1
    if (b === '无日期') return -1
    return a.localeCompare(b)
  })

  return (
    <div style={{ padding: 12 }}>
      {sortedKeys.length === 0 && <Empty description="暂无记录" style={{ padding: 48 }} />}
      {sortedKeys.map(key => (
        <div key={key} style={{ marginBottom: 24 }}>
          <div style={{
            fontWeight: 600, marginBottom: 8, padding: '6px 12px',
            background: '#f0f5ff', borderRadius: 6, color: '#1d4ed8',
            fontSize: 13,
          }}>
            📅 {key} <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 12 }}>({groups.get(key)!.length})</span>
          </div>
          <Row gutter={[8, 8]}>
            {groups.get(key)!.map(r => (
              <Col xs={24} sm={12} md={8} lg={6} key={r.id}>
                <div
                  onClick={() => onRowClick?.(r)}
                  style={{
                    padding: 10, border: '1px solid #e5e7eb', borderRadius: 6,
                    background: '#fff', cursor: 'pointer', fontSize: 13,
                  }}
                >
                  <div style={{ fontWeight: 500, marginBottom: 2 }}>{String(r[titleCol] ?? r.id)}</div>
                  <div style={{ fontSize: 11, color: '#9ca3af' }}>ID: {r.id}</div>
                </div>
              </Col>
            ))}
          </Row>
        </div>
      ))}
    </div>
  )
}

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

// ─────────────── 表格显示设置 Dialog（全局用户设置） ───────────────

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
      title="表格显示设置"
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
        保存到浏览器，对所有数据表生效
      </div>
    </Modal>
  )
}

// ─────────────── 一些保留但暂隐藏的图标引用（让打包器知道没丢依赖） ───────────────

void DownOutlined; void CloseOutlined; void Switch


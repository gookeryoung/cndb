/** dashboard 画布（ADR 0023 P0 只读 / P1 编辑）.
 *
 * - 解析 `view_options`（`normalizeDashboard` 唯一契约入口），非法配置退化为可读空态；
 * - 12 列固定栅格 + `normalizeLayout` 收敛越界/上浮消洞，窄屏按单列塌陷；
 * - 单表客户端取数：每个 widget 的 query 在本地过滤/排序/截断；
 * - P1 编辑态：拖拽 / 缩放 / 方向键微调 / 5 种预设 / 属性面板 / 撤销栈，
 *   所有变更留在本地 draft，显式保存（⌘/Ctrl+S）才写库，Esc 回滚。
 */

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { App as AntApp, Button, Empty, Modal, Tooltip } from 'antd'
import {
  CloseOutlined, CopyOutlined, EditOutlined, FileImageOutlined, FilePdfOutlined, LinkOutlined,
  LogoutOutlined, RedoOutlined, ReloadOutlined, SaveOutlined, SettingOutlined, UndoOutlined,
} from '@ant-design/icons'
import type { Field, RowResponse, View } from '@/api'
import {
  DashboardConfigError,
  normalizeDashboard,
  serializeDashboard,
  type DashboardConfig,
  type DashboardNormalizeOptions,
  type DashboardWidget,
} from './dashboardModel'
import { clampBox, collapseNarrow, normalizeLayout, type WidgetBox } from './dashboardLayout'
import { applyWidgetQuery } from './dashboardQuery'
import { resolveQueryGlobals, type DashboardGlobals } from './dashboardGlobals'
import { useDashboardDraft } from './useDashboardDraft'
import { useDashboardData } from './useDashboardData'
import type { DashboardExportFormat } from './dashboardExport'
import GlobalFilterBar from './GlobalFilterBar'
import type { DashboardTemplateMode } from './DashboardTemplateDialog'
import { buildDashboardDataset } from './chart/dataset'
import { missingChartRoles } from './widgets/ChartWidget'
import { aggregateKpi } from './widgets/KpiWidget'
import type { Dataset, KpiDataset, TableDataset, DatasetMeta } from './chart/types'
import { VIEW_FETCH_ALL_LIMIT } from '../../useGridData'
import DashboardGrid from './DashboardGrid'
import ChartWidget from './widgets/ChartWidget'
import KpiWidget from './widgets/KpiWidget'
import TableWidget from './widgets/TableWidget'
import TextWidget from './widgets/TextWidget'

/** 属性面板仅在点击「属性」/选中组件后出现，按需加载（不进 DashboardView chunk） */
const DashboardConfigDrawer = lazy(() => import('./DashboardConfigDrawer'))
/** 模板对话框仅在点击「另存 / 从模板创建」时出现，按需加载（不进 DashboardView chunk） */
const DashboardTemplateDialog = lazy(() => import('./DashboardTemplateDialog'))

/** 窄屏阈值（px）：低于该宽度按单列塌陷（ADR 0023 D4） */
export const DASHBOARD_NARROW_WIDTH = 720

/**
 * 读/存路径的跨表解析选项：目标表字段不在前端预取，可用性由服务端保存校验与
 * 取数层降级共同兜底（ADR 0023 D8）。
 */
const CROSS_TABLE_OPTIONS: DashboardNormalizeOptions = {
  resolveTableFields: () => null,
  allowUnavailableTargets: true,
}

export interface DashboardViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  /** 工作区 / 数据表 id：大表走服务端批量取数时需要（ADR 0023 §4） */
  workspaceId?: string | number
  tableId?: string | number
  total?: number
  onRowClick?: (r: RowResponse) => void
  /** 行数据加载中 */
  loading?: boolean
  /** 行数据加载失败文案 */
  error?: string | null
  /** 是否可编辑视图配置（无权限时只展示编辑入口隐藏） */
  canEdit?: boolean
  /** 显式保存：由页面层写 view_options 并触发持久化 */
  onSave?: (options: Record<string, unknown>) => void
  /** 小表路径的刷新回调（定时刷新 / 手动刷新；由页面层重新拉行集） */
  onRefresh?: () => void
  /** 只读展示态（`present=1`）：隐藏编辑 / 模板入口、禁用行详情，保留刷新 / 导出 / 退出（ADR 0023 / 原 0077 D7） */
  presenting?: boolean
  /** 退出只读展示（由页面层移除 `present` 参数） */
  onExitPresent?: () => void
  /** 复制当前 dashboard 的登录态只读链接；未提供时不渲染入口 */
  onCopyShareLink?: () => void
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < DASHBOARD_NARROW_WIDTH,
  )
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = () => setNarrow(window.innerWidth < DASHBOARD_NARROW_WIDTH)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return narrow
}

/** Dataset 是否为空（决定卡片空态；与各 kind 的数据形状一一对应） */
function datasetIsEmpty(dataset: Dataset): boolean {
  switch (dataset.kind) {
    case 'category': return dataset.categories.length === 0
    case 'pie': return dataset.items.length === 0
    case 'scatter': return dataset.points.length === 0
    case 'histogram': return dataset.bins.length === 0
    case 'boxplot': return dataset.categories.length === 0
    case 'radar': return dataset.series.length === 0
    case 'funnel': return dataset.items.length === 0
    case 'gauge': return dataset.value === null
    case 'heatmap': return dataset.values.length === 0
    case 'treemap': return dataset.nodes.length === 0
    case 'kpi': return dataset.value === null
    case 'table': return dataset.rows.length === 0
    default: return true
  }
}

/** 解析配置；成功返回 config，失败返回可读路径 */
export function parseDashboardConfig(
  raw: Record<string, unknown> | null | undefined,
  fields: Field[],
  options?: DashboardNormalizeOptions,
): { config: DashboardConfig | null; error: string | null } {
  try {
    return { config: normalizeDashboard(raw ?? {}, fields, options ?? CROSS_TABLE_OPTIONS), error: null }
  } catch (e) {
    if (e instanceof DashboardConfigError) return { config: null, error: e.path }
    return { config: null, error: e instanceof Error ? e.message : String(e) }
  }
}

export default function DashboardView({
  rows,
  fields,
  view,
  workspaceId,
  tableId,
  total = 0,
  onRowClick,
  loading = false,
  error = null,
  canEdit = false,
  onSave,
  onRefresh,
  presenting = false,
  onExitPresent,
  onCopyShareLink,
}: DashboardViewProps) {
  const narrow = useNarrow()
  const { message } = AntApp.useApp()
  const parsed = useMemo(
    () => parseDashboardConfig(view?.view_options as Record<string, unknown> | undefined, fields),
    [view?.view_options, fields],
  )
  // 非法配置时的兜底空配置必须保持引用稳定，否则 reset effect 会逐帧触发无限重渲染
  const emptyConfig = useMemo(() => normalizeDashboard({}, fields), [fields])
  const baseline = parsed.config ?? emptyConfig
  const [editing, setEditing] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  /** 模板对话框模式；null 表示关闭 */
  const [templateMode, setTemplateMode] = useState<DashboardTemplateMode | null>(null)
  /** 整屏导出进行中的格式（null = 空闲）；同一时刻只允许一个导出任务 */
  const [exporting, setExporting] = useState<DashboardExportFormat | null>(null)
  /** 整屏导出捕获容器：全局筛选栏 + 画布主体，不含工具栏（ADR 0023 / 原 0077 D4） */
  const exportAreaRef = useRef<HTMLDivElement>(null)
  const draft = useDashboardDraft(baseline)
  const baselineRef = useRef(baseline)
  baselineRef.current = baseline

  /** 全局筛选值（id → 值）；配置里删掉的筛选项自动剪枝 */
  const [globals, setGlobals] = useState<DashboardGlobals>({})
  const globalIds = useMemo(
    () => baseline.global_filters.map((f) => f.id).join(','),
    [baseline.global_filters],
  )
  useEffect(() => {
    const known = new Set(globalIds.split(',').filter(Boolean))
    setGlobals((current) => {
      const kept = Object.entries(current).filter(([id]) => known.has(id))
      return kept.length === Object.keys(current).length ? current : Object.fromEntries(kept)
    })
  }, [globalIds])

  // 数据口径（I3）：总行数超过客户端上限、或画布内存在跨表 widget 时改走服务端
  // 批量取数（客户端只有基表行集，跨表组必须由服务端按表扫描，ADR 0023 D8）
  const hasCrossTable = useMemo(
    () => draft.config.widgets.some((w) => w.query.table_id != null),
    [draft.config.widgets],
  )
  const useServer = total > VIEW_FETCH_ALL_LIMIT || hasCrossTable
  const serverData = useDashboardData({
    wid: workspaceId, tid: tableId, view, enabled: useServer, globals,
  })

  // 非编辑态跟随服务端配置；编辑态不覆盖本地草稿（I5）
  useEffect(() => {
    if (!editing) draft.reset(baseline)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseline, editing])

  // 展示态不允许停留在编辑态（入口已隐藏，防止带着编辑态进入展示链接）
  useEffect(() => {
    if (!presenting || !editing) return
    setEditing(false)
    setSelectedId(null)
    setDrawerOpen(false)
    draft.reset(baselineRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presenting, editing])

  // 选中项被撤销/删除后清理
  useEffect(() => {
    if (selectedId && !draft.config.widgets.some((w) => w.id === selectedId)) {
      setSelectedId(null)
      setDrawerOpen(false)
    }
  }, [draft.config.widgets, selectedId])

  /** `{{global.x}}` 在取数前统一改写 filters（ADR 0023 P3），不在渲染层拼条件 */
  const resolvedQueries = useMemo(() => {
    const out = new Map<string, { query: DashboardWidget['query']; unapplied: number }>()
    for (const widget of draft.config.widgets) {
      out.set(widget.id, resolveQueryGlobals(widget.query, globals))
    }
    return out
  }, [draft.config.widgets, globals])

  const rowsByWidget = useMemo(() => {
    const out = new Map<string, RowResponse[]>()
    for (const widget of draft.config.widgets) {
      const resolved = resolvedQueries.get(widget.id)
      out.set(widget.id, applyWidgetQuery(rows, resolved?.query ?? widget.query))
    }
    return out
  }, [draft.config.widgets, resolvedQueries, rows])

  /** 小表路径：客户端装配 Dataset（与 ChartWidget 内部回退同构，统一供口径提示） */
  const clientDatasets = useMemo<Map<string, Dataset>>(() => {
    const out = new Map<string, Dataset>()
    if (useServer) return out
    const overall = Math.max(total, rows.length)
    for (const widget of draft.config.widgets) {
      if (widget.type === 'text') continue
      const rowsForWidget = rowsByWidget.get(widget.id) ?? []
      const meta: DatasetMeta = {
        scanned: rowsForWidget.length,
        total: overall,
        truncated: rowsForWidget.length < overall,
        cached: false,
        unapplied_globals: resolvedQueries.get(widget.id)?.unapplied ?? 0,
      }
      if (widget.type === 'chart') {
        if (missingChartRoles(widget, fields).length) continue
        out.set(widget.id, { ...buildDashboardDataset(rowsForWidget, fields, widget.chart), meta })
      } else if (widget.type === 'kpi') {
        const { field, agg } = widget.kpi.value
        out.set(widget.id, {
          kind: 'kpi', field, agg, value: aggregateKpi(rowsForWidget, field, agg), meta,
        })
      } else {
        out.set(widget.id, {
          kind: 'table',
          columns: widget.table.columns,
          rows: rowsForWidget.slice(0, widget.table.row_limit),
          total: rowsForWidget.length,
          meta,
        })
      }
    }
    return out
  }, [useServer, draft.config.widgets, rowsByWidget, resolvedQueries, rows.length, fields, total])

  const datasets = useServer ? serverData.datasets : clientDatasets
  const widgetErrors = useServer ? serverData.errors : new Map<string, string>()

  /** 刷新入口：大表重取服务端聚合，小表由页面层重新拉行集 */
  const refreshRef = useRef<() => void>(() => {})
  refreshRef.current = () => {
    if (useServer) serverData.refetch()
    else onRefresh?.()
  }

  // 定时刷新（ADR 0023 P3）：后台标签页不轮询，回到前台后由下一次 tick 恢复
  const refreshInterval = baseline.settings.refresh_interval
  useEffect(() => {
    if (!refreshInterval) return
    const timer = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      refreshRef.current()
    }, refreshInterval * 1000)
    return () => window.clearInterval(timer)
  }, [refreshInterval])

  const metaById = useMemo(() => {
    const out = new Map<string, string>()
    for (const [id, dataset] of datasets) {
      const meta = dataset.meta
      if (!meta) continue
      const unapplied = meta.unapplied_globals ?? resolvedQueries.get(id)?.unapplied ?? 0
      out.set(id, `样本 ${meta.scanned} / 总行数 ${meta.total}${meta.cached ? ' · 缓存' : ''}${
        unapplied ? ' · 未应用全局筛选' : ''}`)
    }
    return out
  }, [datasets, resolvedQueries])

  const exitEditing = () => {
    setEditing(false)
    setSelectedId(null)
    setDrawerOpen(false)
  }

  /** 应用模板：进入编辑态并整份替换草稿（基线不变 → dirty，需显式保存） */
  const applyTemplateConfig = (next: DashboardConfig) => {
    draft.replace(next)
    setEditing(true)
    setSelectedId(next.widgets[0]?.id ?? null)
  }

  const save = () => {
    const options = serializeDashboard(draft.config)
    try {
      normalizeDashboard(options, fields, CROSS_TABLE_OPTIONS)
    } catch (e) {
      const path = e instanceof DashboardConfigError ? e.path : '配置'
      message.error(`画布配置无效：${path}`)
      return
    }
    onSave?.(options)
    draft.markSaved()
    exitEditing()
    if (!onSave) message.success('画布已保存')
  }

  const requestExit = () => {
    if (!draft.dirty) {
      draft.reset(baselineRef.current)
      exitEditing()
      return
    }
    Modal.confirm({
      title: '放弃未保存的画布修改？',
      content: '退出编辑后，本次拖拽与配置变更不会保留。',
      okText: '放弃修改',
      cancelText: '继续编辑',
      okButtonProps: { danger: true },
      onOk: () => {
        draft.reset(baselineRef.current)
        exitEditing()
      },
    })
  }

  // ⌘/Ctrl+S 保存；Esc 退出编辑（有未保存变更时确认）
  useEffect(() => {
    if (!editing) return
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        save()
      } else if (e.key === 'Escape' && !drawerOpen) {
        e.preventDefault()
        requestExit()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  // 非法配置：空态而非炸页
  if (!parsed.config) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description={`画布配置无效：${parsed.error}`} data-testid="dashboard-config-error" />
      </div>
    )
  }

  const config = draft.config
  /** 展示态禁止行详情：只展示聚合结果，不打开行抽屉（ADR 0023 / 原 0077 D7 / I3） */
  const effectiveRowClick = presenting ? undefined : onRowClick
  /** 数据就绪判定：页面行集或服务端批量取数仍在加载时不导出，避免截到骨架屏 */
  const dataLoading = loading || (useServer && serverData.loading)
  const exportDisabled = dataLoading || exporting !== null || config.widgets.length === 0

  /** 整屏导出：等待两帧让骨架屏退出 / 图表完成 setOption，再捕获专用容器 */
  const handleExport = async (format: DashboardExportFormat) => {
    const target = exportAreaRef.current
    if (!target) {
      message.error('未找到可导出的画布')
      return
    }
    if (exportDisabled) return
    setExporting(format)
    try {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => { requestAnimationFrame(() => resolve()) })
      })
      // 编排模块按需加载：html2canvas / jsPDF 相关链路不得进入画布主 chunk（ADR 0023 / 原 0077 D10）
      const { exportDashboard } = await import('./dashboardExport')
      await exportDashboard(target, view?.name, format)
      message.success('导出完成')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally {
      setExporting(null)
    }
  }

  const globalBar = config.global_filters.length > 0 ? (
    <GlobalFilterBar
      filters={config.global_filters}
      values={globals}
      onChange={setGlobals}
    />
  ) : null

  const patchLayout = (id: string, patch: Partial<WidgetBox>) => {
    const widget = config.widgets.find((w) => w.id === id)
    if (!widget) return
    const box = clampBox({ ...widget.layout, ...patch }, config.canvas.cols)
    const all = config.widgets.map((w) => (w.id === id ? box : w.layout))
    draft.setLayouts(normalizeLayout(all, config.canvas.cols, id))
  }

  const renderBody = (widget: DashboardWidget) => {
    // 跨表 widget 的客户端行集不可用（只有基表 rows），未拿到服务端 Dataset 时按空集渲染
    const rowsForWidget = widget.query.table_id != null ? [] : (rowsByWidget.get(widget.id) ?? [])
    const dataset = datasets.get(widget.id)
    if (widget.type === 'chart') {
      return (
        <ChartWidget
          widget={widget}
          rows={rowsForWidget}
          fields={fields}
          dataset={dataset}
          onRowClick={effectiveRowClick}
        />
      )
    }
    if (widget.type === 'kpi') {
      const kpi = dataset?.kind === 'kpi' ? (dataset as KpiDataset) : undefined
      return <KpiWidget widget={widget} rows={rowsForWidget} dataset={kpi} />
    }
    if (widget.type === 'text') return <TextWidget widget={widget} />
    const table = dataset?.kind === 'table' ? (dataset as TableDataset) : undefined
    return <TableWidget widget={widget} rows={rowsForWidget} dataset={table} onRowClick={effectiveRowClick} />
  }

  const isWidgetEmpty = (widget: DashboardWidget) => {
    if (widget.type === 'text') return false
    const rowsForWidget = widget.query.table_id != null ? [] : (rowsByWidget.get(widget.id) ?? [])
    if (!useServer && rowsForWidget.length === 0) return true
    const dataset = datasets.get(widget.id)
    return dataset ? datasetIsEmpty(dataset) : rowsForWidget.length === 0
  }

  const toolbar = (
    <div
      data-testid="dashboard-toolbar"
      style={{
        flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
        borderBottom: '1px solid var(--cn-border)', background: 'var(--cn-bg-container)',
      }}
    >
      {editing ? (
        <>
          <Button type="primary" size="small" icon={<SaveOutlined />} onClick={save} data-testid="dashboard-save">
            保存
          </Button>
          <Button size="small" icon={<CloseOutlined />} onClick={requestExit} data-testid="dashboard-cancel">
            退出
          </Button>
          <Button size="small" icon={<UndoOutlined />} disabled={!draft.canUndo} onClick={draft.undo} data-testid="dashboard-undo">
            撤销
          </Button>
          <Button size="small" icon={<RedoOutlined />} disabled={!draft.canRedo} onClick={draft.redo} data-testid="dashboard-redo">
            重做
          </Button>
          <Button size="small" icon={<SettingOutlined />} onClick={() => setDrawerOpen(true)} data-testid="dashboard-properties">
            属性
          </Button>
          <Button size="small" icon={<CopyOutlined />} onClick={() => setTemplateMode('apply')} data-testid="dashboard-template-apply-open">
            应用模板
          </Button>
          <Button size="small" icon={<CopyOutlined />} onClick={() => setTemplateMode('save')} data-testid="dashboard-template-save-open">
            另存为模板
          </Button>
          {draft.dirty && (
            <span style={{ marginLeft: 'auto', fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-secondary)' }}>有未保存修改</span>
          )}
        </>
      ) : (
        <>
          {!presenting && canEdit && (
            <Tooltip title={narrow ? '窄屏下请使用桌面宽度编辑画布' : '拖拽 / 缩放 / 预设 / 属性面板'}>
              <Button
                size="small"
                icon={<EditOutlined />}
                disabled={narrow}
                onClick={() => {
                  setEditing(true)
                  setSelectedId(config.widgets[0]?.id ?? null)
                }}
                data-testid="dashboard-edit"
              >
                编辑画布
              </Button>
            </Tooltip>
          )}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => refreshRef.current()}
            data-testid="dashboard-refresh"
          >
            刷新
          </Button>
          {refreshInterval > 0 && (
            <span style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-secondary)' }}>
              每 {refreshInterval}s 自动刷新
            </span>
          )}
          {!presenting && canEdit && (
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => setTemplateMode('apply')}
              data-testid="dashboard-template-create"
            >
              从模板创建
            </Button>
          )}
          {!presenting && onCopyShareLink && (
            <Button
              size="small"
              icon={<LinkOutlined />}
              onClick={onCopyShareLink}
              data-testid="dashboard-copy-share"
            >
              复制只读链接
            </Button>
          )}
          <Button
            size="small"
            icon={<FileImageOutlined />}
            loading={exporting === 'png'}
            disabled={exportDisabled}
            onClick={() => { void handleExport('png') }}
            data-testid="dashboard-export-png"
          >
            导出 PNG
          </Button>
          <Button
            size="small"
            icon={<FilePdfOutlined />}
            loading={exporting === 'pdf'}
            disabled={exportDisabled}
            onClick={() => { void handleExport('pdf') }}
            data-testid="dashboard-export-pdf"
          >
            导出 PDF
          </Button>
          {presenting && onExitPresent && (
            <Button
              size="small"
              icon={<LogoutOutlined />}
              onClick={onExitPresent}
              data-testid="dashboard-exit-present"
            >
              退出展示
            </Button>
          )}
        </>
      )}
    </div>
  )

  const templateDialog = templateMode !== null
    ? (
        <Suspense fallback={null}>
          <DashboardTemplateDialog
            open
            mode={templateMode}
            config={config}
            fields={fields}
            workspaceId={workspaceId}
            defaultName={view?.name ? `${view.name}模板` : '未命名模板'}
            onClose={() => setTemplateMode(null)}
            onApply={applyTemplateConfig}
          />
        </Suspense>
      )
    : null

  // 空画布：只读保持 P0 空态；编辑态给添加提示
  if (config.widgets.length === 0 && !editing) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {toolbar}
        {templateDialog}
        <div
          ref={exportAreaRef}
          data-testid="dashboard-export-area"
          style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
        >
          {globalBar}
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty description="画布还没有组件（视图设置中添加）" data-testid="dashboard-empty" />
          </div>
        </div>
      </div>
    )
  }

  let gridConfig = config
  if (narrow) {
    const boxes = collapseNarrow(normalizeLayout(config.widgets.map((w) => w.layout), config.canvas.cols), config.canvas.cols)
    const byId = new Map(boxes.map((b) => [b.id, b]))
    gridConfig = { ...config, widgets: config.widgets.map((w) => ({ ...w, layout: { ...byId.get(w.id)!, id: w.id } })) }
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {toolbar}
      {templateDialog}
      {editing && (
        <div
          data-testid="dashboard-edit-hint"
          style={{ flexShrink: 0, padding: '4px 12px', fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-secondary)' }}
        >
          拖拽标题栏移动 · 右下角缩放 · 选中后方向键微调（Shift+方向键改尺寸）· Ctrl/⌘+S 保存 · Esc 退出
        </div>
      )}
      {/* 整屏导出捕获区：全局筛选栏 + 画布主体，不含工具栏与编辑提示（ADR 0023 / 原 0077 D4） */}
      <div
        ref={exportAreaRef}
        data-testid="dashboard-export-area"
        style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
      >
        {globalBar}
        <DashboardGrid
          config={gridConfig}
          editing={editing}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id)
            if (id) setDrawerOpen(true)
          }}
          onLayout={draft.setLayouts}
          onRemove={draft.removeWidget}
          renderBody={renderBody}
          isWidgetEmpty={isWidgetEmpty}
          loading={dataLoading}
          error={error}
          errorById={widgetErrors}
          metaById={metaById}
        />
      </div>
      {editing && drawerOpen && (
        <Suspense fallback={null}>
          <DashboardConfigDrawer
            open
            onClose={() => setDrawerOpen(false)}
            config={config}
            fields={fields}
            workspaceId={workspaceId}
            baseTableId={tableId}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onPatchWidget={draft.updateWidget}
            onPatchLayout={patchLayout}
            onRemoveWidget={draft.removeWidget}
            onAddWidget={(type) => {
              const id = draft.addWidget(type, fields)
              if (id) {
                setSelectedId(id)
                setDrawerOpen(true)
              }
            }}
            onApplyPreset={draft.applyPreset}
            onUpdateCanvas={draft.updateCanvas}
            onUpdateSettings={draft.updateSettings}
          />
        </Suspense>
      )}
    </div>
  )
}

/** 供测试与外部复用的默认配置工厂 */
export function emptyDashboardConfig(fields: Field[] = []): DashboardConfig {
  return normalizeDashboard({}, fields)
}

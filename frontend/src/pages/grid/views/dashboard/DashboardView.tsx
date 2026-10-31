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
  CloseOutlined, EditOutlined, RedoOutlined, SaveOutlined, SettingOutlined, UndoOutlined,
} from '@ant-design/icons'
import type { Field, RowResponse, View } from '@/api'
import {
  DashboardConfigError,
  normalizeDashboard,
  serializeDashboard,
  type DashboardConfig,
  type DashboardWidget,
} from './dashboardModel'
import { clampBox, collapseNarrow, normalizeLayout, type WidgetBox } from './dashboardLayout'
import { applyWidgetQuery } from './dashboardQuery'
import { useDashboardDraft } from './useDashboardDraft'
import DashboardGrid from './DashboardGrid'
import ChartWidget from './widgets/ChartWidget'
import KpiWidget from './widgets/KpiWidget'
import TableWidget from './widgets/TableWidget'
import TextWidget from './widgets/TextWidget'

/** 属性面板仅在点击「属性」/选中组件后出现，按需加载（不进 DashboardView chunk） */
const DashboardConfigDrawer = lazy(() => import('./DashboardConfigDrawer'))

/** 窄屏阈值（px）：低于该宽度按单列塌陷（ADR 0023 D4） */
export const DASHBOARD_NARROW_WIDTH = 720

export interface DashboardViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
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

/** 解析配置；成功返回 config，失败返回可读路径 */
export function parseDashboardConfig(
  raw: Record<string, unknown> | null | undefined,
  fields: Field[],
): { config: DashboardConfig | null; error: string | null } {
  try {
    return { config: normalizeDashboard(raw ?? {}, fields), error: null }
  } catch (e) {
    if (e instanceof DashboardConfigError) return { config: null, error: e.path }
    return { config: null, error: e instanceof Error ? e.message : String(e) }
  }
}

export default function DashboardView({
  rows,
  fields,
  view,
  onRowClick,
  loading = false,
  error = null,
  canEdit = false,
  onSave,
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
  const draft = useDashboardDraft(baseline)
  const baselineRef = useRef(baseline)
  baselineRef.current = baseline

  // 非编辑态跟随服务端配置；编辑态不覆盖本地草稿（I5）
  useEffect(() => {
    if (!editing) draft.reset(baseline)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseline, editing])

  // 选中项被撤销/删除后清理
  useEffect(() => {
    if (selectedId && !draft.config.widgets.some((w) => w.id === selectedId)) {
      setSelectedId(null)
      setDrawerOpen(false)
    }
  }, [draft.config.widgets, selectedId])

  const rowsByWidget = useMemo(() => {
    const out = new Map<string, RowResponse[]>()
    for (const widget of draft.config.widgets) {
      out.set(widget.id, applyWidgetQuery(rows, widget.query))
    }
    return out
  }, [draft.config.widgets, rows])

  const exitEditing = () => {
    setEditing(false)
    setSelectedId(null)
    setDrawerOpen(false)
  }

  const save = () => {
    const options = serializeDashboard(draft.config)
    try {
      normalizeDashboard(options, fields)
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

  const patchLayout = (id: string, patch: Partial<WidgetBox>) => {
    const widget = config.widgets.find((w) => w.id === id)
    if (!widget) return
    const box = clampBox({ ...widget.layout, ...patch }, config.canvas.cols)
    const all = config.widgets.map((w) => (w.id === id ? box : w.layout))
    draft.setLayouts(normalizeLayout(all, config.canvas.cols, id))
  }

  const renderBody = (widget: DashboardWidget) => {
    const rowsForWidget = rowsByWidget.get(widget.id) ?? []
    if (widget.type === 'chart') {
      return <ChartWidget widget={widget} rows={rowsForWidget} fields={fields} onRowClick={onRowClick} />
    }
    if (widget.type === 'kpi') return <KpiWidget widget={widget} rows={rowsForWidget} />
    if (widget.type === 'text') return <TextWidget widget={widget} />
    return <TableWidget widget={widget} rows={rowsForWidget} />
  }

  const isWidgetEmpty = (widget: DashboardWidget) =>
    widget.type !== 'text' && (rowsByWidget.get(widget.id) ?? []).length === 0

  const toolbar = canEdit && (
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
          {draft.dirty && (
            <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--cn-text-secondary)' }}>有未保存修改</span>
          )}
        </>
      ) : (
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
    </div>
  )

  // 空画布：只读保持 P0 空态；编辑态给添加提示
  if (config.widgets.length === 0 && !editing) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {toolbar}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Empty description="画布还没有组件（视图设置中添加）" data-testid="dashboard-empty" />
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
      {editing && (
        <div
          data-testid="dashboard-edit-hint"
          style={{ flexShrink: 0, padding: '4px 12px', fontSize: 12, color: 'var(--cn-text-secondary)' }}
        >
          拖拽标题栏移动 · 右下角缩放 · 选中后方向键微调（Shift+方向键改尺寸）· Ctrl/⌘+S 保存 · Esc 退出
        </div>
      )}
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
        loading={loading}
        error={error}
      />
      {editing && drawerOpen && (
        <Suspense fallback={null}>
          <DashboardConfigDrawer
            open
            onClose={() => setDrawerOpen(false)}
            config={config}
            fields={fields}
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

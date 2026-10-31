/** dashboard 只读画布（ADR 0023 P0）.
 *
 * - 解析 `view_options`（`normalizeDashboard` 唯一契约入口），非法配置退化为可读空态；
 * - 12 列固定栅格 + `normalizeLayout` 收敛越界/上浮消洞，窄屏按单列塌陷；
 * - 单表客户端取数：每个 widget 的 query 在本地过滤/排序/截断；
 * - 图表/KPI/文本/明细四类组件；拖拽、全局筛选联动、服务端聚合在 P1/P2 补齐。
 */

import { useEffect, useMemo, useState } from 'react'
import { Empty } from 'antd'
import type { Field, RowResponse, View } from '@/api'
import {
  DashboardConfigError,
  normalizeDashboard,
  type DashboardConfig,
  type DashboardWidget,
} from './dashboardModel'
import { collapseNarrow, normalizeLayout, toGridStyle } from './dashboardLayout'
import { applyWidgetQuery } from './dashboardQuery'
import WidgetShell from './WidgetShell'
import ChartWidget from './widgets/ChartWidget'
import KpiWidget from './widgets/KpiWidget'
import TableWidget from './widgets/TableWidget'
import TextWidget from './widgets/TextWidget'

/** 窄屏阈值（px）：低于该宽度按单列塌陷（ADR 0023 D3） */
export const DASHBOARD_NARROW_WIDTH = 720

const DEFAULT_TITLES: Record<DashboardWidget['type'], string> = {
  chart: '图表',
  kpi: '指标',
  text: '说明',
  table: '明细',
}

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
}: DashboardViewProps) {
  const narrow = useNarrow()
  const parsed = useMemo(
    () => parseDashboardConfig(view?.view_options as Record<string, unknown> | undefined, fields),
    [view?.view_options, fields],
  )

  const rowsByWidget = useMemo(() => {
    const config = parsed.config
    if (!config) return new Map<string, RowResponse[]>()
    const out = new Map<string, RowResponse[]>()
    for (const widget of config.widgets) {
      out.set(widget.id, applyWidgetQuery(rows, widget.query))
    }
    return out
  }, [parsed.config, rows])

  if (!parsed.config) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty
          description={`画布配置无效：${parsed.error}`}
          data-testid="dashboard-config-error"
        />
      </div>
    )
  }

  const config = parsed.config
  if (config.widgets.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="画布还没有组件（视图设置中添加）" data-testid="dashboard-empty" />
      </div>
    )
  }

  const boxes = normalizeLayout(config.widgets.map((w) => w.layout), config.canvas.cols)
  const layout = narrow ? collapseNarrow(boxes, config.canvas.cols) : boxes
  const boxById = new Map(layout.map((b) => [b.id, b]))

  return (
    <div
      data-testid="dashboard-canvas"
      style={{
        flex: 1, minHeight: 0, overflow: 'auto',
        display: 'grid',
        gridTemplateColumns: `repeat(${config.canvas.cols}, minmax(0, 1fr))`,
        gridAutoRows: `${config.canvas.row_height}px`,
        gap: config.canvas.gap,
        padding: config.canvas.padding,
        alignContent: 'start',
        background: 'var(--cn-bg-page)',
      }}
    >
      {config.widgets.map((widget) => {
        const rowsForWidget = rowsByWidget.get(widget.id) ?? []
        const isEmpty = widget.type !== 'text' && rowsForWidget.length === 0
        return (
          <div key={widget.id} style={{ ...toGridStyle(boxById.get(widget.id) ?? widget.layout), minWidth: 0, minHeight: 0 }}>
            <WidgetShell
              title={widget.title || DEFAULT_TITLES[widget.type]}
              error={error ?? undefined}
              loading={loading}
              empty={isEmpty}
              testId={`dashboard-widget-${widget.id}`}
            >
              {widget.type === 'chart' ? (
                <ChartWidget widget={widget} rows={rowsForWidget} fields={fields} onRowClick={onRowClick} />
              ) : widget.type === 'kpi' ? (
                <KpiWidget widget={widget} rows={rowsForWidget} />
              ) : widget.type === 'text' ? (
                <TextWidget widget={widget} />
              ) : (
                <TableWidget widget={widget} rows={rowsForWidget} />
              )}
            </WidgetShell>
          </div>
        )
      })}
    </div>
  )
}

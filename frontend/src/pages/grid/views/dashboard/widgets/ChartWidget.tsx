/** dashboard 图表组件：把 dashboard 契约映射到既有 ChartCard 配置（ADR 0023 P0）.
 *
 * 不引入第二套图表实现 —— 复用 ChartView 的 ChartCard（ECharts 生命周期、空态、点击语义），
 * 仅做 DashboardChart -> ChartConfig 的角色映射。
 */

import type { Field, RowResponse } from '@/api'
import { ChartCard } from '../../ChartView'
import type { ChartConfig } from '../../chartBoard'
import type { DashboardChartWidget } from '../dashboardModel'

/** dashboard chart 角色声明 -> ChartConfig（扁平键单图形态） */
export function toChartConfig(widget: DashboardChartWidget): ChartConfig {
  const { chart } = widget
  const cfg: ChartConfig = {
    chart_type: chart.type,
    aggregation: chart.agg,
    show_stats_panel: false,
  }
  if (chart.type === 'scatter') {
    cfg.x_field = chart.x
    cfg.y_field = chart.y[0]
  } else if (chart.type === 'histogram') {
    cfg.measure_field = chart.y[0]
  } else {
    cfg.dimension_field = chart.x
    cfg.measure_field = chart.y[0]
    if (chart.series && (chart.type === 'bar' || chart.type === 'line')) {
      cfg.group_field = chart.series
    }
  }
  return cfg
}

export interface ChartWidgetProps {
  widget: DashboardChartWidget
  rows: RowResponse[]
  fields: Field[]
  onRowClick?: (r: RowResponse) => void
}

export default function ChartWidget({ widget, rows, fields, onRowClick }: ChartWidgetProps) {
  const cfg = toChartConfig(widget)
  return (
    <ChartCard
      cfg={cfg}
      rows={rows}
      fields={fields}
      onRowClick={onRowClick}
      minHeight={0}
      emptyConfigTestId={`dashboard-chart-empty-${widget.id}`}
    />
  )
}

/** dashboard KPI 组件：单指标聚合展示（ADR 0023 P0）.
 *
 * 聚合口径与图表一致（count 为非空值计数；数值字段支持 sum/avg/min/max），
 * 周期对比与服务端聚合在 P1/P2 补齐，P0 只展示当前值。
 */

import type { RowResponse } from '@/api'
import { extractNumbers } from '../../chartBoard'
import type { DashboardAggregation, DashboardKpiWidget } from '../dashboardModel'
import type { KpiDataset } from '../chart/types'

/** 按聚合方式计算单指标值（无有效样本时返回 null） */
export function aggregateKpi(rows: RowResponse[], field: string, agg: DashboardAggregation): number | null {
  const nums = extractNumbers(rows, field)
  switch (agg) {
    case 'count':
      // count 为非空值个数（对齐 SQL COUNT(col)），文本/日期字段同样适用
      return rows.reduce((n, r) => n + (r[field] == null || r[field] === '' ? 0 : 1), 0)
    case 'sum':
      return nums.length ? nums.reduce((a, b) => a + b, 0) : null
    case 'avg':
      return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
    case 'min':
      return nums.length ? Math.min(...nums) : null
    case 'max':
      return nums.length ? Math.max(...nums) : null
    case 'median': {
      if (!nums.length) return null
      const sorted = [...nums].sort((a, b) => a - b)
      const mid = Math.floor(sorted.length / 2)
      return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
    }
    default:
      return null
  }
}

/** KPI 数值格式化：整数原样，浮点保留最多 2 位并去掉尾零 */
export function formatKpi(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  if (Number.isInteger(value)) return value.toLocaleString('zh-CN')
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

export interface KpiWidgetProps {
  widget: DashboardKpiWidget
  rows: RowResponse[]
  /** 服务端聚合结果（大表路径）；客户端路径不传，按行集本地聚合 */
  dataset?: KpiDataset
}

export default function KpiWidget({ widget, rows, dataset }: KpiWidgetProps) {
  const { field, agg } = widget.kpi.value
  const result = dataset ? dataset.value : aggregateKpi(rows, field, agg)
  const aggLabel: Record<DashboardAggregation, string> = {
    sum: '合计', avg: '均值', count: '计数', min: '最小值', max: '最大值', median: '中位数',
  }
  return (
    <div
      data-testid={`dashboard-kpi-${widget.id}`}
      style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', minHeight: 0 }}
    >
      <div
        data-testid={`dashboard-kpi-value-${widget.id}`}
        style={{
          fontSize: 26, fontWeight: 600, lineHeight: 1.2, color: 'var(--cn-text-primary)',
          fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}
      >
        {formatKpi(result)}
      </div>
      <div style={{ marginTop: 4, fontSize: 12, color: 'var(--cn-text-secondary)' }}>
        {aggLabel[agg]} · {field}
      </div>
    </div>
  )
}

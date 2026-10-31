/** dashboard 图表组件：Dataset → option（ADR 0023 P2）.
 *
 * 只消费 `Dataset`：小表由客户端 `buildDashboardDataset` 装配，
 * 大表由服务端批量端点直传；两条链路同构，渲染层单一路径。
 */

import { useMemo, useRef } from 'react'
import { Button, Empty, Tooltip } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { Field, RowResponse } from '@/api'
import { useTheme } from '@/theme/ThemeProvider'
import type { DashboardChartWidget } from '../dashboardModel'
import { getChartTypeDef } from '../chart/chartRegistry'
import { buildDashboardDataset } from '../chart/dataset'
import ChartCanvas, { type ChartCanvasHandle } from '../chart/ChartCanvas'
import type { Dataset, ThemeColors } from '../chart/types'

/** 主题相关颜色（getComputedStyle 读 CSS 变量；jsdom/SSR 回退浅色默认值） */
function readThemeColors(): ThemeColors {
  const read = (name: string, fallback: string): string => {
    if (typeof document === 'undefined') return fallback
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  }
  return {
    text: read('--cn-text-primary', '#1f2937'),
    secondary: read('--cn-text-secondary', '#6b7280'),
    border: read('--cn-border', '#e5e7eb'),
    bg: read('--cn-bg-container', '#ffffff'),
  }
}

/** 检查必填角色；返回缺失项中文标签（空数组表示配齐） */
export function missingChartRoles(widget: DashboardChartWidget, fields: Field[]): string[] {
  const chart = widget.chart
  const has = (name?: string) => !!name && fields.some((f) => f.name === name)
  const out: string[] = []
  if (chart.type !== 'histogram' && chart.type !== 'gauge' && !has(chart.x)) out.push('维度字段')
  if (!chart.y.length || !chart.y.every(has)) out.push('度量字段')
  if ((chart.type === 'heatmap' || chart.type === 'treemap') && !has(chart.series)) out.push('第二维字段')
  return out
}

export interface ChartWidgetProps {
  widget: DashboardChartWidget
  rows: RowResponse[]
  fields: Field[]
  /** 服务端批量聚合结果（大表路径）；客户端路径不传 */
  dataset?: Dataset
  onRowClick?: (r: RowResponse) => void
}

export default function ChartWidget({ widget, rows, fields, dataset, onRowClick }: ChartWidgetProps) {
  const { mode: themeMode } = useTheme()
  const handleRef = useRef<ChartCanvasHandle>(null)
  const { chart } = widget
  const def = getChartTypeDef(chart.type)

  const suppliedDataset = dataset && dataset.kind !== 'kpi' && dataset.kind !== 'table' ? dataset : undefined
  const missing = useMemo(() => missingChartRoles(widget, fields), [widget, fields])
  const data = useMemo<Dataset | null>(() => {
    if (missing.length) return null
    if (suppliedDataset) return suppliedDataset
    return buildDashboardDataset(rows, fields, chart)
  }, [suppliedDataset, missing.length, rows, fields, chart])

  const option = useMemo(
    () => (data ? def.buildOption(data, chart, readThemeColors(), widget.display) : null),
    // themeMode 进依赖：主题切换时 getComputedStyle 已更新，需重建 option
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, chart, widget.display, def, themeMode],
  )

  const rowsRef = useRef(rows)
  rowsRef.current = rows
  const onRowClickRef = useRef(onRowClick)
  onRowClickRef.current = onRowClick

  const handleExport = () => {
    const url = handleRef.current?.getDataURL()
    if (!url) return
    const name = `${widget.title || def.label}${chart.x ? `-${chart.x}` : ''}`.replace(/[\\/:*?"<>|]/g, '_')
    const link = document.createElement('a')
    link.href = url
    link.download = `${name}.png`
    link.click()
  }

  return (
    <div data-testid={`dashboard-chart-${widget.id}`} style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex' }}>
      <ChartCanvas
        ref={handleRef}
        option={option}
        testId={`dashboard-chart-container-${widget.id}`}
        onSeriesClick={(params) => {
          if (params.seriesType !== 'scatter' || data?.kind !== 'scatter') return
          const rowId = data.rowIds[params.dataIndex ?? -1]
          if (rowId == null) return
          // 大表路径行集未全量下发，只带 id 触发详情抽屉的按需拉取
          const row = rowsRef.current.find((r) => r.id === rowId) ?? ({ id: rowId } as RowResponse)
          onRowClickRef.current?.(row)
        }}
        empty={(
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={missing.length
              ? `图表需配置${missing.join('与')}（视图设置）`
              : '当前筛选下无数据'}
            data-testid={`dashboard-chart-empty-${widget.id}`}
          />
        )}
      />
      {option && (
        <Tooltip title="导出 PNG">
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={handleExport}
            data-testid={`dashboard-chart-export-${widget.id}`}
            style={{ position: 'absolute', top: 0, right: 0, zIndex: 2, opacity: 0.75 }}
          />
        </Tooltip>
      )}
    </div>
  )
}

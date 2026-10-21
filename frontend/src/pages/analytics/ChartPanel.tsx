/** 可视化配置 —— 图表类型 / 聚合方式 / 维度·指标·系列 / 标题.
 *
 * 单行塞 4 个 Select 在 400px 配置栏里必然换行错位，这里改成「标签在上、控件在下」
 * 的两列网格：扫一眼就知道每个下拉框对应什么语义，行高也更稳定。
 */

import { Input, Select } from 'antd'
import { LineChartOutlined } from '@ant-design/icons'
import type { AnalyticsChart, AnalyticsAgg } from '@/api/analytics'
import { AnalyticsBox } from './AnalyticsBox'
import { AGG_OPTIONS, CHART_TYPES, chartUsesAggregation } from './analyticsModel'

interface Props {
  chart: AnalyticsChart
  onChange: (chart: AnalyticsChart) => void
  /** 可选维度 / 指标：字段 + 公式键 */
  options: Array<{ value: string; label: string }>
  /** 系列分组只允许原始字段 */
  tableFields: string[]
}

export function ChartPanel({ chart, onChange, options, tableFields }: Props) {
  const usesAgg = chartUsesAggregation(chart.type)
  const xLabel = chart.type === 'scatter' ? 'X 数值列' : chart.type === 'histogram' ? '分箱列' : '维度 / X 轴'
  const yLabel = chart.type === 'scatter' ? 'Y 数值列' : '指标 / Y 轴'

  return (
    <AnalyticsBox
      title="可视化"
      icon={<LineChartOutlined />}
      className="cn-an-box--chart"
      footer={<span className="cn-an-foot-hint">散点 / 直方图 / 箱线图不使用维度聚合</span>}
    >
      <div className="cn-an-grid cn-an-grid--2">
        <div className="cn-an-field">
          <span className="cn-an-label">图表类型</span>
          <Select
            size="small"
            data-testid="analytics-chart-type"
            value={chart.type}
            options={CHART_TYPES}
            onChange={v => onChange({ ...chart, type: v })}
          />
        </div>
        <div className="cn-an-field">
          <span className="cn-an-label">聚合方式</span>
          <Select
            size="small"
            data-testid="analytics-chart-aggregation"
            value={chart.aggregation ?? 'sum'}
            options={AGG_OPTIONS}
            disabled={!usesAgg}
            title={usesAgg ? '维度聚合方式' : '当前图表类型不使用维度聚合'}
            onChange={v => onChange({ ...chart, aggregation: v as AnalyticsAgg })}
          />
        </div>
        <div className="cn-an-field cn-an-span2">
          <span className="cn-an-label">{xLabel}</span>
          <Select
            size="small"
            data-testid="analytics-chart-x"
            placeholder={chart.type === 'scatter' ? 'X 数值列' : '维度 / 分箱列（X 轴）'}
            value={chart.x ?? undefined}
            allowClear
            showSearch
            optionFilterProp="label"
            options={options}
            onChange={v => onChange({ ...chart, x: v ?? null })}
          />
        </div>
        <div className="cn-an-field cn-an-span2">
          <span className="cn-an-label">{yLabel}</span>
          <Select
            size="small"
            data-testid="analytics-chart-y"
            placeholder={chart.type === 'scatter' ? 'Y 数值列' : '指标（被聚合的列）'}
            value={chart.y ?? undefined}
            allowClear
            showSearch
            optionFilterProp="label"
            options={options}
            onChange={v => onChange({ ...chart, y: v ?? null })}
          />
        </div>
        <div className="cn-an-field">
          <span className="cn-an-label">系列分组</span>
          <Select
            size="small"
            data-testid="analytics-chart-series"
            placeholder="可选"
            value={chart.series ?? undefined}
            allowClear
            options={tableFields.map(n => ({ value: n, label: n }))}
            onChange={v => onChange({ ...chart, series: v ?? null })}
          />
        </div>
        <div className="cn-an-field">
          <span className="cn-an-label">图表标题</span>
          <Input
            size="small"
            data-testid="analytics-chart-title"
            placeholder="可选"
            value={chart.title ?? ''}
            onChange={e => onChange({ ...chart, title: e.target.value })}
          />
        </div>
      </div>
    </AnalyticsBox>
  )
}

/** 可视化配置卡片 —— 图表类型 / 聚合方式 / 维度·指标·系列 / 标题. */

import { Card, Input, Select, Space, Typography } from 'antd'
import type { AnalyticsChart, AnalyticsAgg } from '@/api/analytics'
import { AGG_OPTIONS, CHART_TYPES, chartUsesAggregation } from './analyticsModel'

const { Text } = Typography

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
  return (
    <Card size="small" title="可视化配置">
      <Space direction="vertical" style={{ width: '100%' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Select
            data-testid="analytics-chart-type"
            style={{ width: 130 }}
            value={chart.type}
            options={CHART_TYPES}
            onChange={v => onChange({ ...chart, type: v })}
          />
          <Select
            data-testid="analytics-chart-aggregation"
            style={{ width: 120 }}
            value={chart.aggregation ?? 'sum'}
            options={AGG_OPTIONS}
            disabled={!usesAgg}
            title={usesAgg ? '维度聚合方式' : '当前图表类型不使用维度聚合'}
            onChange={v => onChange({ ...chart, aggregation: v as AnalyticsAgg })}
          />
          <Select
            data-testid="analytics-chart-x"
            style={{ width: 220 }}
            placeholder={chart.type === 'scatter' ? 'X 数值列' : '维度 / 分箱列（X 轴）'}
            value={chart.x ?? undefined}
            allowClear
            showSearch
            optionFilterProp="label"
            options={options}
            onChange={v => onChange({ ...chart, x: v ?? null })}
          />
          <Select
            data-testid="analytics-chart-y"
            style={{ width: 220 }}
            placeholder={chart.type === 'scatter' ? 'Y 数值列' : '指标（被聚合的列）'}
            value={chart.y ?? undefined}
            allowClear
            showSearch
            optionFilterProp="label"
            options={options}
            onChange={v => onChange({ ...chart, y: v ?? null })}
          />
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <Select
            data-testid="analytics-chart-series"
            style={{ width: 220 }}
            placeholder="系列分组字段（柱状/折线可选）"
            value={chart.series ?? undefined}
            allowClear
            options={tableFields.map(n => ({ value: n, label: n }))}
            onChange={v => onChange({ ...chart, series: v ?? null })}
          />
          <Input
            data-testid="analytics-chart-title"
            style={{ width: 260 }}
            placeholder="图表标题（可选）"
            value={chart.title ?? ''}
            onChange={e => onChange({ ...chart, title: e.target.value })}
          />
        </div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          聚合方式对柱状图 / 折线图 / 饼图生效；散点、直方图、箱线图按原始数值分布绘制。
        </Text>
      </Space>
    </Card>
  )
}

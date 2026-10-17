/** 分组汇总配置卡片 —— 分组字段 + 指标（字段/公式 × 聚合方式）+ 排序 + Top N. */

import { Button, Card, Input, InputNumber, Select, Space, Tooltip, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import type { AnalyticsAgg, AnalyticsSummary, AnalyticsSummaryMetric } from '@/api/analytics'
import { AGG_OPTIONS, summarySortOptions } from './analyticsModel'

const { Text } = Typography

interface Props {
  summary: AnalyticsSummary
  onChange: (summary: AnalyticsSummary) => void
  /** 分组字段候选（仅原始字段） */
  groupOptions: Array<{ value: string; label: string }>
  /** 指标来源候选（字段 + 公式键） */
  metricOptions: Array<{ value: string; label: string }>
}

/** 分组汇总配置：配置了就随「运行分析」一起返回汇总表 */
export function SummaryPanel({ summary, onChange, groupOptions, metricOptions }: Props) {
  const patchMetric = (index: number, patch: Partial<AnalyticsSummaryMetric>) => {
    onChange({
      ...summary,
      metrics: summary.metrics.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    })
  }

  const addMetric = () => {
    const first = metricOptions[0]?.value ?? ''
    onChange({
      ...summary,
      metrics: [...summary.metrics, { field: first, agg: 'sum', label: '' }],
    })
  }

  const removeMetric = (index: number) => {
    onChange({ ...summary, metrics: summary.metrics.filter((_, i) => i !== index) })
  }

  const sortOptions = summarySortOptions(summary)

  return (
    <Card
      size="small"
      title="分组汇总"
      extra={
        <Tooltip title="按维度分组后计算指标（基于全量扫描行），可排序并只保留前 N 组；留空分组字段则输出全局合计。">
          <QuestionCircleOutlined style={{ color: '#94a3b8' }} />
        </Tooltip>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>分组字段</Text>
          <Select
            data-testid="analytics-summary-group"
            style={{ width: 220 }}
            placeholder="按字段分组（留空 = 全局合计）"
            allowClear
            showSearch
            optionFilterProp="label"
            value={summary.group_by ?? undefined}
            options={groupOptions}
            onChange={v => onChange({ ...summary, group_by: v ?? null })}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>排序</Text>
          <Select
            data-testid="analytics-summary-sort"
            style={{ width: 180 }}
            placeholder="不排序"
            allowClear
            value={summary.sort_by ?? undefined}
            options={sortOptions}
            onChange={v => onChange({ ...summary, sort_by: v ?? null })}
          />
          <Select
            data-testid="analytics-summary-sort-order"
            style={{ width: 90 }}
            value={summary.sort_order ?? 'desc'}
            options={[
              { value: 'desc', label: '降序' },
              { value: 'asc', label: '升序' },
            ]}
            onChange={v => onChange({ ...summary, sort_order: v as 'asc' | 'desc' })}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>Top N</Text>
          <InputNumber
            data-testid="analytics-summary-topn"
            style={{ width: 100 }}
            min={1}
            max={1000}
            placeholder="全部"
            value={summary.top_n ?? null}
            onChange={v => onChange({ ...summary, top_n: typeof v === 'number' ? v : null })}
          />
        </div>

        {summary.metrics.map((metric, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <Select
              data-testid={`analytics-summary-metric-field-${i}`}
              style={{ width: 220 }}
              placeholder="指标来源（字段 / 公式）"
              showSearch
              optionFilterProp="label"
              value={metric.field || undefined}
              options={metricOptions}
              onChange={v => patchMetric(i, { field: v })}
            />
            <Select
              data-testid={`analytics-summary-metric-agg-${i}`}
              style={{ width: 100 }}
              value={metric.agg}
              options={AGG_OPTIONS}
              onChange={v => patchMetric(i, { agg: v as AnalyticsAgg })}
            />
            <Input
              data-testid={`analytics-summary-metric-label-${i}`}
              style={{ width: 200 }}
              placeholder="展示名（可选）"
              value={metric.label ?? ''}
              onChange={e => patchMetric(i, { label: e.target.value })}
            />
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              aria-label="删除汇总指标"
              onClick={() => removeMetric(i)}
            />
          </div>
        ))}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={addMetric}>
            添加指标
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {summary.metrics.length === 0
              ? '未配置指标时不生成汇总表'
              : `运行后输出 ${summary.top_n ? `前 ${summary.top_n} 组` : '全部'}分组结果`}
          </Text>
        </div>
      </Space>
    </Card>
  )
}

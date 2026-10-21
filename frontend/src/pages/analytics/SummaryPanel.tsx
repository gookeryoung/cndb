/** 分组汇总配置 —— 分组字段 + 指标（字段/公式 × 聚合方式）+ 排序 + Top N.
 *
 * 配置栏宽度固定，故一律用「标签在上 / 控件在下」的网格；
 * 指标行压成紧凑的 [来源][聚合][展示名][删除] 四段，与公式行同一视觉节奏。
 */

import { Button, Input, InputNumber, Select, Tooltip } from 'antd'
import { DeleteOutlined, GroupOutlined, PlusOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import type { AnalyticsAgg, AnalyticsSummary, AnalyticsSummaryMetric } from '@/api/analytics'
import { AnalyticsBox } from './AnalyticsBox'
import { AGG_OPTIONS, summarySortOptions } from './analyticsModel'

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
    <AnalyticsBox
      title="分组汇总"
      icon={<GroupOutlined />}
      className="cn-an-box--summary"
      extra={
        <Tooltip title="按维度分组后计算指标（基于全量扫描行），可排序并只保留前 N 组；留空分组字段则输出全局合计">
          <QuestionCircleOutlined className="cn-an-box-hint" aria-label="分组汇总说明" />
        </Tooltip>
      }
      footer={
        <>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addMetric}>
            添加指标
          </Button>
          <span className="cn-an-foot-hint">
            {summary.metrics.length === 0
              ? '未配置指标时不生成汇总表'
              : `运行后输出${summary.top_n ? `前 ${summary.top_n} 组` : '全部分组'}结果`}
          </span>
        </>
      }
    >
      <div className="cn-an-grid cn-an-grid--2">
        <div className="cn-an-field cn-an-span2">
          <span className="cn-an-label">分组字段</span>
          <Select
            size="small"
            data-testid="analytics-summary-group"
            placeholder="按字段分组（留空 = 全局合计）"
            allowClear
            showSearch
            optionFilterProp="label"
            value={summary.group_by ?? undefined}
            options={groupOptions}
            onChange={v => onChange({ ...summary, group_by: v ?? null })}
          />
        </div>
        <div className="cn-an-field cn-an-span2">
          <span className="cn-an-label">排序指标</span>
          <Select
            size="small"
            data-testid="analytics-summary-sort"
            placeholder="不排序"
            allowClear
            value={summary.sort_by ?? undefined}
            options={sortOptions}
            onChange={v => onChange({ ...summary, sort_by: v ?? null })}
          />
        </div>
        <div className="cn-an-field">
          <span className="cn-an-label">方向</span>
          <Select
            size="small"
            data-testid="analytics-summary-sort-order"
            value={summary.sort_order ?? 'desc'}
            options={[
              { value: 'desc', label: '降序' },
              { value: 'asc', label: '升序' },
            ]}
            onChange={v => onChange({ ...summary, sort_order: v as 'asc' | 'desc' })}
          />
        </div>
        <div className="cn-an-field">
          <span className="cn-an-label">Top N</span>
          <InputNumber
            size="small"
            style={{ width: '100%' }}
            data-testid="analytics-summary-topn"
            min={1}
            max={1000}
            placeholder="全部"
            value={summary.top_n ?? null}
            onChange={v => onChange({ ...summary, top_n: typeof v === 'number' ? v : null })}
          />
        </div>
      </div>

      {summary.metrics.map((metric, i) => (
        <div key={i} className="cn-an-metric">
          <Select
            size="small"
            className="cn-an-metric-field"
            data-testid={`analytics-summary-metric-field-${i}`}
            placeholder="指标来源（字段 / 公式）"
            showSearch
            optionFilterProp="label"
            value={metric.field || undefined}
            options={metricOptions}
            onChange={v => patchMetric(i, { field: v })}
          />
          <Select
            size="small"
            className="cn-an-metric-agg"
            data-testid={`analytics-summary-metric-agg-${i}`}
            value={metric.agg}
            options={AGG_OPTIONS}
            onChange={v => patchMetric(i, { agg: v as AnalyticsAgg })}
          />
          <Input
            size="small"
            className="cn-an-metric-label"
            data-testid={`analytics-summary-metric-label-${i}`}
            placeholder="展示名（可选）"
            value={metric.label ?? ''}
            onChange={e => patchMetric(i, { label: e.target.value })}
          />
          <Button
            className="cn-an-metric-del"
            type="text"
            danger
            icon={<DeleteOutlined />}
            aria-label="删除汇总指标"
            onClick={() => removeMetric(i)}
          />
        </div>
      ))}
    </AnalyticsBox>
  )
}

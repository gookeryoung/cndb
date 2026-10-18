/** RecommendationPanel 单测 —— 字段角色 chips / 一键应用 / 典型示例 / 加载与空态. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { RecommendationPanel } from './RecommendationPanel'
import { renderProviders } from '@/test/render-providers'
import type { AnalyticsRecommendations } from '@/api/analytics'

const RECOMMENDATIONS: AnalyticsRecommendations = {
  table_id: 20,
  row_count: 500,
  sampled_rows: 200,
  truncated: true,
  fields: [
    { name: '产品', field_type: 'text', role: 'dimension', reason: '低基数文本列，适合分组', cardinality: 4, completeness: 1 },
    { name: '日期', field_type: 'date', role: 'time', reason: '时间字段，适合趋势图' },
    { name: '产量', field_type: 'number', role: 'metric', reason: '数值列，适合求和/平均', cardinality: 200, completeness: 0.98 },
    { name: '合格数', field_type: 'number', role: 'metric', reason: '数值列' },
    { name: '批次号', field_type: 'text', role: 'identifier', reason: '高基数唯一值' },
    { name: '备注', field_type: 'text', role: 'ignored', reason: '非结构化文本' },
  ],
  formulas: [
    { key: 'pass_rate', label: '合格率', expr: 'round([合格数] / [产量] * 100, 2)', reason: '两个数值列比值' },
  ],
  chart: {
    chart: { type: 'bar', x: '产品', y: 'pass_rate', aggregation: 'avg', title: '推荐图表' },
    reason: '维度 + 指标组合适合柱状图',
  },
  summary: {
    summary: {
      group_by: '产品',
      metrics: [{ field: 'pass_rate', agg: 'avg', label: '平均合格率' }],
      sort_by: null,
      sort_order: 'desc',
      top_n: 5,
    },
    reason: '按产品分组看平均合格率',
  },
  examples: [
    {
      id: 'quality',
      name: '质量分析',
      description: '按产品对比合格率',
      formulas: [{ key: 'pass_rate', label: '合格率', expr: 'round([合格数] / [产量] * 100, 2)' }],
      chart: { type: 'line', x: '产品', y: 'pass_rate', aggregation: 'avg', title: '质量趋势' },
      summary: null,
      reason: '典型质量分析场景',
    },
  ],
}

type PanelProps = ComponentProps<typeof RecommendationPanel>

function renderPanel(props: Partial<PanelProps> = {}) {
  const handlers = {
    onSelectDimension: vi.fn(),
    onSelectMetric: vi.fn(),
    onSelectTime: vi.fn(),
    onApplyChart: vi.fn(),
    onApplySummary: vi.fn(),
    onApplyFormulas: vi.fn(),
    onApplyExample: vi.fn(),
  }
  const result = renderProviders(
    <RecommendationPanel
      recommendations={RECOMMENDATIONS}
      tableName="产品批次"
      {...handlers}
      {...props}
    />,
  )
  return { ...result, handlers }
}

describe('RecommendationPanel', () => {
  it('按角色分组渲染字段 chips，并展示采样信息与推荐理由', () => {
    renderPanel()

    expect(screen.getByTestId('analytics-recommend')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-recommend-dimension-产品')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-recommend-time-日期')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-recommend-metric-产量')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-recommend-metric-合格数')).toBeInTheDocument()
    // 角色分组标题
    expect(screen.getByTestId('analytics-recommend-group-dimension')).toHaveTextContent('维度')
    expect(screen.getByTestId('analytics-recommend-group-time')).toHaveTextContent('时间')
    expect(screen.getByTestId('analytics-recommend-group-metric')).toHaveTextContent('指标')
    // 标识 / 忽略字段不参与联动，不渲染为 chip
    expect(screen.queryByText('批次号')).not.toBeInTheDocument()
    expect(screen.queryByTestId('analytics-recommend-group-identifier')).not.toBeInTheDocument()
    // 采样信息（truncated 提示）
    expect(screen.getByTestId('analytics-recommend-meta')).toHaveTextContent('200/500')
    expect(screen.getByTestId('analytics-recommend-meta')).toHaveTextContent('已截断')
    // 推荐公式 chip
    expect(screen.getByTestId('analytics-recommend-formula-pass_rate')).toHaveTextContent('合格率')
  })

  it('点击推荐维度 / 指标 / 时间字段分别回调对应设置动作', () => {
    const { handlers } = renderPanel()

    fireEvent.click(screen.getByTestId('analytics-recommend-dimension-产品'))
    expect(handlers.onSelectDimension).toHaveBeenCalledWith('产品')

    fireEvent.click(screen.getByTestId('analytics-recommend-metric-产量'))
    expect(handlers.onSelectMetric).toHaveBeenCalledWith('产量')

    fireEvent.click(screen.getByTestId('analytics-recommend-time-日期'))
    expect(handlers.onSelectTime).toHaveBeenCalledWith('日期')
  })

  it('应用推荐图表 / 汇总 / 公式回调携带推荐配置', () => {
    const { handlers } = renderPanel()

    fireEvent.click(screen.getByTestId('analytics-recommend-chart'))
    expect(handlers.onApplyChart).toHaveBeenCalledWith(RECOMMENDATIONS.chart!.chart)

    fireEvent.click(screen.getByTestId('analytics-recommend-summary'))
    expect(handlers.onApplySummary).toHaveBeenCalledWith(RECOMMENDATIONS.summary!.summary)

    fireEvent.click(screen.getByTestId('analytics-recommend-formulas'))
    expect(handlers.onApplyFormulas).toHaveBeenCalledWith(RECOMMENDATIONS.formulas)
  })

  it('典型示例 Dropdown：列出 name / description，点击后回调 example', async () => {
    const { handlers } = renderPanel()

    fireEvent.click(screen.getByTestId('analytics-recommend-examples'))
    const item = await screen.findByTestId('analytics-recommend-example-quality')
    expect(item).toHaveTextContent('质量分析')
    expect(item).toHaveTextContent('按产品对比合格率')

    fireEvent.click(item)
    expect(handlers.onApplyExample).toHaveBeenCalledWith(RECOMMENDATIONS.examples[0])
  })

  it('加载中显示骨架，不显示空态', () => {
    renderPanel({ loading: true })
    expect(screen.getByTestId('analytics-recommend-loading')).toBeInTheDocument()
    expect(screen.queryByText('暂无推荐')).not.toBeInTheDocument()
    expect(screen.queryByTestId('analytics-recommend-dimension-产品')).not.toBeInTheDocument()
  })

  it('无推荐 / 接口失败：空态静默降级，不阻塞手动配置', () => {
    const { unmount } = renderPanel({ recommendations: null })
    expect(screen.getByText('暂无推荐')).toBeInTheDocument()
    unmount()

    renderPanel({ recommendations: null, error: true })
    expect(screen.getByText(/智能推荐服务暂不可用/)).toBeInTheDocument()
    expect(screen.queryByTestId('analytics-recommend-loading')).not.toBeInTheDocument()
  })

  it('无推荐图表 / 汇总时对应按钮禁用', () => {
    renderPanel({
      recommendations: { ...RECOMMENDATIONS, chart: null, summary: null, examples: [] },
    })
    expect(screen.getByTestId('analytics-recommend-chart')).toBeDisabled()
    expect(screen.getByTestId('analytics-recommend-summary')).toBeDisabled()
    expect(screen.getByTestId('analytics-recommend-examples')).toBeDisabled()
  })
})

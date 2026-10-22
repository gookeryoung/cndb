/** 分析 AI 纯逻辑单测（ADR 0020 P3）：解读输入构造 / 生成结果归一化 / warnings 收敛. */

import { describe, expect, it } from 'vitest'
import type { AnalyticsComputeResponse } from '@/api/analytics'
import {
  MAX_AI_EXPLAIN_ROWS,
  applySuggestionConfig,
  buildExplainPayload,
  buildExplainRows,
  suggestionName,
  suggestionWarnings,
} from './analyticsAi'

function makeResult(overrides: Partial<AnalyticsComputeResponse> = {}): AnalyticsComputeResponse {
  return {
    rows: [{ id: 1, 产品: 'A', pass_rate: 96 }],
    total: 1,
    truncated: false,
    table_fields: ['产品'],
    columns: [],
    summary: null,
    ...overrides,
  }
}

describe('buildExplainRows', () => {
  it('优先使用分组汇总行（与「分析结论」语义一致）', () => {
    const result = makeResult({
      summary: {
        group_by: '产品',
        group_label: '产品',
        columns: [{ key: 'avg(pass_rate)', label: '平均合格率', agg: 'avg', source: 'pass_rate' }],
        rows: [{ group: 'A', 'avg(pass_rate)': 96 }, { group: 'B', 'avg(pass_rate)': 89 }],
        group_count: 2,
        truncated: false,
      },
    })
    expect(buildExplainRows(result)).toEqual([
      { group: 'A', 'avg(pass_rate)': 96 },
      { group: 'B', 'avg(pass_rate)': 89 },
    ])
  })

  it('未配置分组汇总时退回派生数据行', () => {
    const result = makeResult({ rows: [{ id: 7, 产品: 'C' }] })
    expect(buildExplainRows(result)).toEqual([{ id: 7, 产品: 'C' }])
  })

  it(`最多 ${MAX_AI_EXPLAIN_ROWS} 行（与后端 MAX_EXPLAIN_ROWS 对齐）且返回浅拷贝`, () => {
    const rows = Array.from({ length: 80 }, (_, i) => ({ id: i, group: `g${i}` }))
    const result = makeResult({
      summary: {
        group_by: 'group',
        group_label: '分组',
        columns: [],
        rows,
        group_count: rows.length,
        truncated: false,
      },
    })
    const explainRows = buildExplainRows(result)
    expect(explainRows).toHaveLength(MAX_AI_EXPLAIN_ROWS)
    expect(explainRows[0]).toEqual({ id: 0, group: 'g0' })
    // 浅拷贝：改拷贝不影响原结果
    explainRows[0].id = 999
    expect((result.summary!.rows[0] as Record<string, unknown>).id).toBe(0)
  })

  it('空结果返回空数组（页面据此提示先运行分析）', () => {
    expect(buildExplainRows(null)).toEqual([])
    expect(buildExplainRows(makeResult({ rows: [] }))).toEqual([])
  })
})

describe('buildExplainPayload', () => {
  it('组装 summary_rows + chart_type + template_id', () => {
    const payload = buildExplainPayload({
      result: makeResult({ rows: [{ id: 1 }] }),
      chartType: 'line',
      templateId: 7,
    })
    expect(payload).toEqual({
      summary_rows: [{ id: 1 }],
      chart_type: 'line',
      template_id: 7,
    })
  })

  it('空 chart_type / 空 template_id 不写入请求体', () => {
    const payload = buildExplainPayload({ result: makeResult(), chartType: '  ', templateId: null })
    expect(payload).toEqual({ summary_rows: [{ id: 1, 产品: 'A', pass_rate: 96 }] })
    expect(payload).not.toHaveProperty('chart_type')
    expect(payload).not.toHaveProperty('template_id')
  })
})

describe('applySuggestionConfig', () => {
  it('归一化 AI 生成的配置（公式 / 图表 / 汇总）', () => {
    const next = applySuggestionConfig({
      formulas: [
        { key: ' pass_rate ', label: '合格率', expr: 'round([合格数] / [产量] * 100, 2)' },
        { key: '', label: '', expr: '' },
      ],
      chart: { type: 'line', x: '产品', y: 'pass_rate', aggregation: 'avg', title: '趋势' },
      summary: {
        group_by: '产品',
        metrics: [{ field: 'pass_rate', agg: 'avg', label: '平均合格率' }],
        sort_by: 'avg(pass_rate)',
        sort_order: 'desc',
        top_n: 3,
      },
      fields: [],
      limit: 1000,
    })
    expect(next.formulas).toHaveLength(1)
    expect(next.formulas[0]).toMatchObject({ key: ' pass_rate ', expr: 'round([合格数] / [产量] * 100, 2)' })
    expect(next.chart).toMatchObject({ type: 'line', x: '产品', y: 'pass_rate', aggregation: 'avg' })
    expect(next.summary.group_by).toBe('产品')
    expect(next.summary.metrics).toHaveLength(1)
    expect(next.summary.top_n).toBe(3)
  })

  it('空配置回退到默认图表与一条空公式（不产生半成品）', () => {
    const next = applySuggestionConfig(null)
    expect(next.formulas).toHaveLength(1)
    expect(next.formulas[0].expr).toBe('')
    expect(next.chart.type).toBe('bar')
    expect(next.summary.metrics).toEqual([])
  })

  it('过滤非法聚合方式与无字段指标', () => {
    const next = applySuggestionConfig({
      formulas: [],
      chart: null,
      summary: {
        group_by: null,
        metrics: [
          { field: '', agg: 'avg' } as never,
          { field: '产量', agg: 'median' as never },
        ],
        sort_by: null,
        sort_order: 'desc',
        top_n: 5,
      },
      fields: [],
      limit: 1000,
    })
    expect(next.summary.metrics).toHaveLength(1)
    expect(next.summary.metrics[0]).toMatchObject({ field: '产量', agg: 'sum' })
  })
})

describe('suggestionWarnings / suggestionName', () => {
  it('warnings 去空、去重并截断到 5 条', () => {
    expect(suggestionWarnings({
      warnings: [' 已按日期截断月份 ', '', '已按日期截断月份', 'a', 'b', 'c', 'd'],
    })).toEqual(['已按日期截断月份', 'a', 'b', 'c', 'd'])
    expect(suggestionWarnings(null)).toEqual([])
  })

  it('空名回退到默认模板名', () => {
    expect(suggestionName({ name: '  ' }, '未命名分析')).toBe('未命名分析')
    expect(suggestionName({ name: ' 各产品合格率 ' }, '未命名分析')).toBe('各产品合格率')
  })
})

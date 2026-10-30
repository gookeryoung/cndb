/** analyticsModel 纯逻辑测试 —— 配置归一化 / 图表映射 / CSV / 公式编辑辅助. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  AGG_OPTIONS,
  AGG_VALUES,
  DEFAULT_CHART,
  EMPTY_SUMMARY,
  applyExampleConfig,
  canRunAnalysis,
  chartConfigured,
  chartUsesAggregation,
  collectFormulaErrors,
  buildTemplateConfig,
  downloadTextFile,
  formatNumber,
  formatRecommendationRole,
  insertAtCursor,
  isDirty,
  mergeFormulas,
  metricKey,
  metricLabel,
  newFormula,
  nonNullRatio,
  normalizeChart,
  normalizeFormulas,
  normalizeSummary,
  recommendationRoleColor,
  safeFileName,
  summaryConfigured,
  summarySortOptions,
  templateOptions,
  templateSnapshot,
  templateTableName,
  toChartConfig,
  toCsv,
  triggerDownload,
} from './analyticsModel'
import type { AnalyticsTemplate } from '@/api/analytics'

const FORMULA = { key: 'pass_rate', label: '合格率(%)', expr: 'round([合格数] / [产量] * 100, 2)' }

afterEach(() => {
  vi.restoreAllMocks()
})

describe('配置归一化', () => {
  it('normalizeFormulas：过滤非法项，空列表回退为一条空公式', () => {
    expect(normalizeFormulas([FORMULA])).toEqual([FORMULA])
    expect(normalizeFormulas([FORMULA, null as never])).toHaveLength(1)
    expect(normalizeFormulas([])).toEqual([newFormula(0)])
    expect(normalizeFormulas(undefined)).toEqual([newFormula(0)])
  })

  it('normalizeChart：缺省聚合补 sum，非法聚合回退 sum，保留标题/字段', () => {
    expect(normalizeChart(null)).toMatchObject({ type: 'bar', aggregation: 'sum', title: '' })
    expect(normalizeChart({ type: 'line', x: '产品', y: '金额', aggregation: 'avg' })).toMatchObject({
      type: 'line',
      x: '产品',
      y: '金额',
      aggregation: 'avg',
    })
    // 旧模板 / 脏数据回退
    expect(normalizeChart({ type: 'bar', aggregation: 'median' as never }).aggregation).toBe('sum')
  })

  it('normalizeSummary：过滤无来源指标、非法排序指标回退 null、默认降序', () => {
    const summary = normalizeSummary({
      group_by: '产品类别',
      metrics: [
        { field: '销售额', agg: 'sum', label: '' },
        { field: '', agg: 'avg' } as never,
      ],
      sort_by: 'sum(销售额)',
      sort_order: 'asc',
      top_n: 3,
    })
    expect(summary.group_by).toBe('产品类别')
    expect(summary.metrics).toEqual([{ field: '销售额', agg: 'sum', label: '' }])
    expect(summary.sort_by).toBe('sum(销售额)')
    expect(summary.sort_order).toBe('asc')
    expect(summary.top_n).toBe(3)

    const fallback = normalizeSummary({ group_by: null, metrics: [{ field: 'x', agg: 'bogus' as never }], sort_by: 'sum(nope)' })
    expect(fallback.metrics[0].agg).toBe('sum')
    expect(fallback.sort_by).toBeNull()
    expect(fallback.sort_order).toBe('desc')
    expect(fallback.top_n).toBeNull()
    expect(normalizeSummary(null)).toMatchObject({ group_by: null, metrics: [] })
  })

  it('buildTemplateConfig：过滤空公式、trim、summary 无指标时不落库', () => {
    const config = buildTemplateConfig({
      formulas: [FORMULA, { key: '  ', label: '', expr: '  ' }],
      chart: { type: 'bar', aggregation: 'avg', x: '产品' },
      summary: { group_by: null, metrics: [], sort_by: null, sort_order: 'desc', top_n: null },
    })
    expect(config.formulas).toEqual([FORMULA])
    expect(config.summary).toBeNull()
    expect(config.chart?.aggregation).toBe('avg')
    expect(config.fields).toEqual([])
    expect(config.limit).toBe(1000)
  })
})

describe('图表映射', () => {
  it('toChartConfig：bar 走维度聚合，scatter 双数值轴，histogram 单列分箱', () => {
    const bar = toChartConfig({ type: 'bar', x: '产品', y: '金额', series: '区域', aggregation: 'avg' })
    expect(bar).toMatchObject({
      chart_type: 'bar',
      dimension_field: '产品',
      measure_field: '金额',
      group_field: '区域',
      aggregation: 'avg',
    })

    const scatter = toChartConfig({ type: 'scatter', x: '产量', y: '销售额' })
    expect(scatter).toMatchObject({ x_field: '产量', y_field: '销售额' })

    const histogram = toChartConfig({ type: 'histogram', x: 'pass_rate' })
    expect(histogram.measure_field).toBe('pass_rate')
  })

  it('chartUsesAggregation：仅 bar / line / pie 使用维度聚合', () => {
    expect(chartUsesAggregation('bar')).toBe(true)
    expect(chartUsesAggregation('pie')).toBe(true)
    expect(chartUsesAggregation('scatter')).toBe(false)
    expect(chartUsesAggregation('histogram')).toBe(false)
    expect(chartUsesAggregation('boxplot')).toBe(false)
  })
})

describe('指标与选项', () => {
  it('metricKey / metricLabel 与后端口径一致', () => {
    expect(metricKey('avg', 'pass_rate')).toBe('avg(pass_rate)')
    expect(metricLabel('avg', 'pass_rate')).toBe('平均(pass_rate)')
    expect(metricLabel('sum', '销售额', '销售额合计')).toBe('销售额合计')
    expect(AGG_OPTIONS.map(o => o.value)).toEqual(AGG_VALUES)
  })

  it('summarySortOptions 只列有来源的指标', () => {
    const options = summarySortOptions({
      group_by: null,
      metrics: [
        { field: '销售额', agg: 'sum' },
        { field: '', agg: 'avg' },
      ],
      sort_by: null,
      sort_order: 'desc',
      top_n: null,
    })
    expect(options).toEqual([{ value: 'sum(销售额)', label: '求和(销售额)' }])
  })

  it('templateOptions 映射 id / name', () => {
    const templates = [
      { id: 1, name: '模板A' },
      { id: 2, name: '模板B' },
    ] as AnalyticsTemplate[]
    expect(templateOptions(templates)).toEqual([
      { value: 1, label: '模板A' },
      { value: 2, label: '模板B' },
    ])
  })
})

describe('智能推荐辅助', () => {
  it('mergeFormulas：单条空公式替换、重复 key / 空表达式跳过、无变化返回原引用', () => {
    const blank = [newFormula(0)]
    expect(mergeFormulas(blank, [
      { key: 'pass_rate', label: '合格率', expr: '[合格数] / [产量]' },
    ])).toEqual([{ key: 'pass_rate', label: '合格率', expr: '[合格数] / [产量]' }])

    const existing = [{ key: 'a', label: '', expr: '[x]' }]
    expect(mergeFormulas(existing, [
      { key: ' a ', label: '', expr: '1' },
      { key: 'b', label: 'B', expr: '2' },
      { key: 'c', label: '', expr: '   ' },
      { key: '', label: '', expr: '3' },
    ])).toEqual([...existing, { key: 'b', label: 'B', expr: '2' }])

    // 无任何可追加内容 → 原引用（调用方可据此判断是否提示）
    expect(mergeFormulas(existing, [{ key: 'a', expr: '1' }])).toBe(existing)
    expect(mergeFormulas(blank, [])).toBe(blank)
  })

  it('applyExampleConfig：formulas / chart / summary 统一经 normalize* 归一化', () => {
    const config = applyExampleConfig({
      formulas: [{ key: 'p', label: '', expr: '[a] / [b]' }, null as never],
      chart: { type: 'line', x: '产品', y: 'p', aggregation: 'median' as never },
      summary: {
        group_by: '产品',
        metrics: [{ field: 'p', agg: 'avg' }, { field: '', agg: 'sum' }],
        sort_by: 'nope',
      },
    })
    expect(config.formulas).toEqual([{ key: 'p', label: '', expr: '[a] / [b]' }])
    expect(config.chart).toMatchObject({ type: 'line', x: '产品', y: 'p', aggregation: 'sum' })
    expect(config.summary.metrics).toEqual([{ field: 'p', agg: 'avg', label: '' }])
    expect(config.summary.sort_by).toBeNull()

    const fallback = applyExampleConfig({ formulas: [], chart: null, summary: null })
    expect(fallback.formulas).toEqual([newFormula(0)])
    expect(fallback.chart).toEqual(DEFAULT_CHART)
    expect(fallback.summary).toMatchObject({ group_by: null, metrics: [], top_n: null })
  })

  it('templateTableName：命中 / 未命中 / 未指定数据表', () => {
    const tables: Array<{ id: number | string; name: string }> = [
      { id: 1, name: '产品批次' },
      { id: 2, name: '其他表' },
    ]
    expect(templateTableName(tables, 1)).toBe('产品批次')
    expect(templateTableName(tables, '2')).toBe('其他表')
    expect(templateTableName(tables, 9)).toBe('表 #9')
    expect(templateTableName(tables, null)).toBe('未指定数据表')
  })

  it('formatRecommendationRole / recommendationRoleColor：角色文案与配色', () => {
    expect(formatRecommendationRole('metric')).toBe('指标')
    expect(formatRecommendationRole('dimension')).toBe('维度')
    expect(formatRecommendationRole('time')).toBe('时间')
    expect(formatRecommendationRole('identifier')).toBe('标识')
    expect(formatRecommendationRole('ignored')).toBe('忽略')
    expect(formatRecommendationRole('unknown')).toBe('unknown')

    expect(recommendationRoleColor('metric')).toBe('green')
    expect(recommendationRoleColor('dimension')).toBe('blue')
    expect(recommendationRoleColor('time')).toBe('purple')
    expect(recommendationRoleColor('other')).toBe('default')
  })
})

describe('未保存修改判定', () => {
  const base = {
    name: '分析',
    description: '说明',
    tableId: 1,
    formulas: [FORMULA],
    chart: { type: 'bar', x: null, y: null, series: null, title: '', aggregation: 'sum' as const },
    summary: { group_by: null, metrics: [], sort_by: null, sort_order: 'desc' as const, top_n: null },
  }

  it('内容相同时不脏，任一字段变化即脏', () => {
    const snapshot = templateSnapshot(base)
    expect(isDirty(snapshot, templateSnapshot({ ...base }))).toBe(false)
    expect(isDirty(snapshot, templateSnapshot({ ...base, name: '改了' }))).toBe(true)
    expect(isDirty(snapshot, templateSnapshot({ ...base, tableId: 2 }))).toBe(true)
    expect(isDirty(snapshot, templateSnapshot({ ...base, formulas: [{ ...FORMULA, expr: '[x]' }] }))).toBe(true)
  })
})

describe('公式本地校验', () => {
  it('空键名 / 重复键名 / 后端错误合并', () => {
    const errors = collectFormulaErrors(
      [
        { key: '', label: '', expr: '1 + 1' },
        { key: 'dup', label: '', expr: '1' },
        { key: 'dup', label: '', expr: '2' },
        { key: 'bad', label: '', expr: '[x]' },
      ],
      { bad: '引用了不存在的字段: x', removed: '旧错误' },
    )
    expect(errors).toEqual({
      '': '键名不能为空',
      dup: '键名重复',
      bad: '引用了不存在的字段: x',
    })
  })

  it('空表达式不报错（尚未填写），仅校验已填写键', () => {
    expect(collectFormulaErrors([{ key: 'a', label: '', expr: '   ' }])).toEqual({})
  })
})

describe('光标插入', () => {
  it('指定位置插入并返回新光标；越界回退末尾', () => {
    expect(insertAtCursor('abc', '[产量]', 1)).toEqual({ value: 'a[产量]bc', caret: 5 })
    expect(insertAtCursor('abc', '[x]', 999)).toEqual({ value: 'abc[x]', caret: 6 })
    expect(insertAtCursor('abc', '[x]', null)).toEqual({ value: 'abc[x]', caret: 6 })
  })
})

describe('CSV 导出', () => {
  it('带 BOM、CRLF，含逗号/引号/换行时按 RFC 4180 转义', () => {
    const csv = toCsv(
      ['列', '值'],
      [
        ['a,b', 1],
        ['say "hi"', null],
        ['多行\n文本', true],
      ],
    )
    expect(csv.startsWith('\uFEFF')).toBe(true)
    expect(csv).toContain('"a,b",1')
    expect(csv).toContain('"say ""hi""",')
    expect(csv).toContain('"多行\n文本",true')
    expect(csv.split('\r\n')).toHaveLength(4)
  })

  it('formatNumber：整数原样、浮点四位有效数字、无效值「—」', () => {
    expect(formatNumber(3)).toBe('3')
    expect(formatNumber(0.123456)).toBe('0.1235')
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber('12')).toBe('—')
    expect(formatNumber(Number.NaN)).toBe('—')
  })

  it('nonNullRatio / safeFileName', () => {
    expect(nonNullRatio(3, 1)).toBe(0.75)
    expect(nonNullRatio(0, 0)).toBeNull()
    expect(safeFileName('a/b:c*?"<>|')).toBe('abc')
    expect(safeFileName('   ')).toBe('分析结果')
  })

  it('downloadTextFile 创建 blob URL 并触发下载', () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    downloadTextFile('a.csv', 'x,y')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })

  it('triggerDownload 生成 <a download> 并点击后移除', () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    triggerDownload('chart.png', 'data:image/png;base64,xxx')
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })
})

describe('运行门禁（canRunAnalysis）', () => {
  const base = {
    tableId: 7 as number | null,
    validFormulaCount: 0,
    chart: { ...DEFAULT_CHART },
    summary: { ...EMPTY_SUMMARY, metrics: [] },
    hasError: false,
  }

  it('chartConfigured：x / y 任一非空即算已配置，空白串不算', () => {
    expect(chartConfigured({ ...DEFAULT_CHART, x: null, y: null })).toBe(false)
    expect(chartConfigured({ ...DEFAULT_CHART, x: '  ' })).toBe(false)
    expect(chartConfigured({ ...DEFAULT_CHART, x: '日期' })).toBe(true)
    expect(chartConfigured({ ...DEFAULT_CHART, y: '产量' })).toBe(true)
  })

  it('summaryConfigured：存在有效指标才算已配置', () => {
    expect(summaryConfigured({ ...EMPTY_SUMMARY, metrics: [] })).toBe(false)
    expect(summaryConfigured({ ...EMPTY_SUMMARY, metrics: [{ agg: 'sum', field: '产量', label: '' }], group_by: '日期' })).toBe(true)
  })

  it('无公式但图表已配置 → 可运行；三者皆空 → 不可运行', () => {
    expect(canRunAnalysis({ ...base, chart: { ...DEFAULT_CHART, x: '日期', y: '产量' } })).toBe(true)
    expect(canRunAnalysis({ ...base, summary: { ...EMPTY_SUMMARY, metrics: [{ agg: 'avg', field: '产量', label: '' }] } })).toBe(true)
    expect(canRunAnalysis(base)).toBe(false)
  })

  it('有公式可运行；未选表或公式有错误时不可运行', () => {
    expect(canRunAnalysis({ ...base, validFormulaCount: 1 })).toBe(true)
    expect(canRunAnalysis({ ...base, validFormulaCount: 1, tableId: null })).toBe(false)
    expect(canRunAnalysis({ ...base, validFormulaCount: 1, hasError: true })).toBe(false)
  })
})

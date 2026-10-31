/** dashboard option 装配测试（ADR 0023 P2）.
 *
 * 每类图一份 option 快照，另覆盖格式化 / 阈值 / 色板 / 双轴 / 百分比堆叠等分支。
 */

import { describe, expect, it } from 'vitest'
import type { Field, RowResponse } from '@/api'
import { makeField } from '@/test/fixtures'
import type { DashboardChart, DashboardChartType, DashboardDisplay } from '../dashboardModel'
import { CHART_TYPE_DEFS, getChartTypeDef } from './chartRegistry'
import {
  buildDatasetOption,
  categoryOption,
  makeFormatter,
  resolvePalette,
  seriesColor,
  thresholdColor,
} from './option'
import type { ThemeColors } from './types'

const THEME: ThemeColors = { text: '#1f1f1f', secondary: '#8c8c8c', border: '#f0f0f0', bg: '#ffffff' }

const FIELDS: Field[] = [
  makeField({ id: 1, name: '类别', field_type: 'text' }),
  makeField({ id: 2, name: '日期', field_type: 'date' }),
  makeField({ id: 3, name: '销售额', field_type: 'number' }),
  makeField({ id: 4, name: '数量', field_type: 'number' }),
]

const ROWS = [
  { id: 1, 类别: '数码', 销售额: 100, 数量: 2, 日期: '2026-01-10' },
  { id: 2, 类别: '家电', 销售额: 50, 数量: 1, 日期: '2026-02-11' },
  { id: 3, 类别: '数码', 销售额: 70, 数量: 3, 日期: '2026-02-12' },
  { id: 4, 类别: '食品', 销售额: 120, 数量: 4, 日期: '2026-03-12' },
  { id: 5, 类别: '家电', 销售额: 40, 数量: 5, 日期: '2026-03-13' },
  { id: 6, 类别: '数码', 销售额: 30, 数量: 6, 日期: '2026-01-20' },
] as unknown as RowResponse[]

const BASE: DashboardChart = {
  type: 'bar',
  x: '类别',
  y: ['销售额'],
  agg: 'sum',
  stack: 'none',
  sort: 'none',
  dual_axis: false,
  format: {},
}

const chart = (patch: Partial<DashboardChart>): DashboardChart => ({ ...BASE, ...patch })

// ── 格式化 / 颜色 helper ───────────────────────────────

describe('格式化与配色 helper', () => {
  it('整数默认去尾零，指定小数位与单位', () => {
    expect(makeFormatter({})(1000)).toBe('1,000')
    expect(makeFormatter({ decimals: 1, unit: '元' })(12.34)).toBe('12.3元')
    expect(makeFormatter({})(Number.NaN)).toBe('—')
  })

  it('阈值配色取达到的最高阈值', () => {
    expect(thresholdColor(10)).toBeUndefined()
    expect(thresholdColor(10, [])).toBeUndefined()
    const thresholds = [{ value: 0, color: '#52c41a' }, { value: 100, color: '#fa8c16' }, { value: 200, color: '#f5222d' }]
    expect(thresholdColor(50, thresholds)).toBe('#52c41a')
    expect(thresholdColor(150, thresholds)).toBe('#fa8c16')
    expect(thresholdColor(300, thresholds)).toBe('#f5222d')
  })

  it('色板解析与循环取色', () => {
    expect(resolvePalette('warm')).toBe(resolvePalette('warm'))
    expect(resolvePalette('dune')).toBe(resolvePalette(undefined))
    expect(seriesColor(8)).toBe(seriesColor(0))
  })
})

// ── 双轴 / 堆叠 / 阈值分支 ─────────────────────────────

describe('categoryOption 分支', () => {
  it('双轴把第二个度量挂到右轴', () => {
    const data = {
      kind: 'category' as const,
      categories: ['A', 'B'],
      series: [
        { name: '销售额', data: [10, 20] },
        { name: '数量', data: [1, 2] },
      ],
    }
    const option = categoryOption(
      data,
      chart({ type: 'combo', dual_axis: true, y: ['销售额', '数量'] }),
      THEME,
    ) as Record<string, unknown>
    const series = option.series as Array<Record<string, unknown>>
    expect(series[0].yAxisIndex).toBe(0)
    expect(series[1].yAxisIndex).toBe(1)
    expect(Array.isArray(option.yAxis)).toBe(true)
  })

  it('百分比堆叠显示面积且使用 stack 分组', () => {
    const data = {
      kind: 'category' as const,
      categories: ['A'],
      series: [
        { name: '销售额', data: [60] },
        { name: '数量', data: [40] },
      ],
    }
    const option = categoryOption(data, chart({ type: 'stack', stack: 'percent' }), THEME) as Record<string, unknown>
    const series = option.series as Array<Record<string, unknown>>
    expect(series[0].stack).toBe('total')
    expect(series[0].areaStyle).toEqual({})
  })

  it('阈值配色逐点覆盖 itemStyle', () => {
    const data = {
      kind: 'category' as const,
      categories: ['A', 'B'],
      series: [{ name: '销售额', data: [50, 150] }],
    }
    const display: DashboardDisplay = {
      thresholds: [{ value: 0, color: '#52c41a' }, { value: 100, color: '#f5222d' }],
    }
    const option = categoryOption(data, chart({}), THEME, display) as Record<string, unknown>
    const points = (option.series as Array<Record<string, unknown>>)[0].data as Array<Record<string, unknown>>
    expect(points[0].itemStyle).toEqual({ color: '#52c41a' })
    expect(points[1].itemStyle).toEqual({ color: '#f5222d' })
  })

  it('show_legend=false 不输出图例', () => {
    const data = {
      kind: 'category' as const,
      categories: ['A'],
      series: [{ name: 'a', data: [1] }, { name: 'b', data: [2] }],
    }
    const option = categoryOption(data, chart({}), THEME, { show_legend: false }) as Record<string, unknown>
    expect(option.legend).toBeUndefined()
  })

  it('heatmap 阈值列表参与 visualMap 色带', () => {
    const data = {
      kind: 'heatmap' as const,
      x: ['A'],
      y: ['B'],
      values: [[0, 0, 5]] as Array<[number, number, number]>,
      max: 5,
    }
    const option = buildDatasetOption(data, chart({ type: 'heatmap' }), THEME, {
      thresholds: [{ value: 0, color: '#e6f7ff' }, { value: 3, color: '#1890ff' }],
    }) as Record<string, unknown>
    const visualMap = option.visualMap as Record<string, unknown>
    expect(visualMap.inRange).toEqual({ color: ['#e6f7ff', '#1890ff'] })
  })
})

// ── 每类图 option 快照 ────────────────────────────────

describe('14 类图 option 快照', () => {
  const cases: Array<[DashboardChartType, DashboardChart]> = [
    ['bar', chart({ type: 'bar' })],
    ['line', chart({ type: 'line' })],
    ['area', chart({ type: 'area' })],
    ['stack', chart({ type: 'stack', series: '日期' })],
    ['combo', chart({ type: 'combo', y: ['销售额', '数量'], dual_axis: true })],
    ['pie', chart({ type: 'pie' })],
    ['scatter', chart({ type: 'scatter', x: '数量' })],
    ['histogram', chart({ type: 'histogram', x: undefined })],
    ['boxplot', chart({ type: 'boxplot' })],
    ['radar', chart({ type: 'radar', y: ['销售额', '数量'] })],
    ['funnel', chart({ type: 'funnel' })],
    ['gauge', chart({ type: 'gauge', target: 500, format: { unit: '元', decimals: 0 } })],
    ['heatmap', chart({ type: 'heatmap', series: '日期' })],
    ['treemap', chart({ type: 'treemap', series: '日期' })],
  ]

  for (const [type, cfg] of cases) {
    it(`${type} 生成 option`, () => {
      const def = getChartTypeDef(type)
      const dataset = def.buildDataset(ROWS, FIELDS, cfg)
      const option = def.buildOption(dataset, cfg, THEME)
      expect(option).toMatchSnapshot()
    })
  }
})

describe('注册表与分派', () => {
  it('14 类图各有一条定义，类型唯一', () => {
    expect(CHART_TYPE_DEFS).toHaveLength(14)
    const types = new Set(CHART_TYPE_DEFS.map((d) => d.type))
    expect(types.size).toBe(14)
  })

  it('未知类型回退柱状图', () => {
    expect(getChartTypeDef('unknown' as DashboardChartType).type).toBe('bar')
  })

  it('非图表 kind 返回 null', () => {
    expect(buildDatasetOption({ kind: 'kpi', field: 'x', agg: 'sum', value: 1 }, chart({}), THEME)).toBeNull()
    expect(buildDatasetOption({ kind: 'table', columns: [], rows: [], total: 0 }, chart({}), THEME)).toBeNull()
  })
})

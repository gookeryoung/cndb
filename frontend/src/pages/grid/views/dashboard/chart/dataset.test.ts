/** dashboard Dataset 装配测试（ADR 0023 P2）.
 *
 * 覆盖 14 类图的 Dataset 形状、日期按月分桶、排序 / TopN / 百分比堆叠、
 * 空值与非法数值跳过，以及与后端 dashboard_data.py 的同构口径。
 */

import { describe, expect, it } from 'vitest'
import type { Field, RowResponse } from '@/api'
import { makeField } from '@/test/fixtures'
import type { DashboardChart, DashboardChartType } from '../dashboardModel'
import {
  buildBoxplotDataset,
  buildCategoryDataset,
  buildDashboardDataset,
  buildFunnelDataset,
  buildGaugeDataset,
  buildHeatmapDataset,
  buildHistogramDataset,
  buildPieDataset,
  buildRadarDataset,
  buildScatterDataset,
  buildTreemapDataset,
} from './dataset'

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

describe('buildCategoryDataset', () => {
  it('按维度聚合多度量，类目按字符串序（未分组恒最后）', () => {
    const data = buildCategoryDataset(
      [...ROWS, { id: 9, 类别: null, 销售额: 10, 数量: 1, 日期: null } as unknown as RowResponse],
      FIELDS,
      chart({ y: ['销售额', '数量'] }),
    )
    expect(data.categories).toEqual(['家电', '食品', '数码', '未分组'])
    expect(data.series.map((s) => s.name)).toEqual(['销售额', '数量'])
    expect(data.series[0].data).toEqual([90, 120, 200, 10])
    expect(data.series[1].data).toEqual([6, 4, 11, 1])
  })

  it('日期维度按月分桶', () => {
    const data = buildCategoryDataset(ROWS, FIELDS, chart({ x: '日期' }))
    expect(data.categories).toEqual(['2026-01', '2026-02', '2026-03'])
    expect(data.series[0].data).toEqual([130, 120, 160])
  })

  it('分组字段把长表转宽表（多度量时系列名带前缀）', () => {
    const data = buildCategoryDataset(ROWS, FIELDS, chart({ series: '日期', y: ['销售额'] }))
    // 日期按月分桶后出现 2026-01 / 2026-02 / 2026-03 三个系列
    expect(data.series.map((s) => s.name)).toEqual(['2026-01', '2026-02', '2026-03'])
  })

  it('sort=y_desc 按数值降序，top_n 其余并「其他」', () => {
    const data = buildCategoryDataset(ROWS, FIELDS, chart({ sort: 'y_desc', top_n: 1 }))
    expect(data.categories).toEqual(['数码', '其他'])
    expect(data.series[0].data).toEqual([200, 210])
  })

  it('sort=x_desc 按维度降序', () => {
    const data = buildCategoryDataset(ROWS, FIELDS, chart({ sort: 'x_desc' }))
    expect(data.categories).toEqual(['数码', '食品', '家电'])
  })

  it('stack=percent 归一为百分比', () => {
    const data = buildCategoryDataset(
      ROWS,
      FIELDS,
      chart({ y: ['销售额', '数量'], stack: 'percent' }),
    )
    // 百分比堆叠按「同一类目各系列合计」归一：家电 = 90 + 6 = 96
    const first = data.series[0].data as number[]
    expect(first[0]).toBeCloseTo((90 / 96) * 100, 4)
  })

  it('count 只计非空值', () => {
    const rows = [{ id: 1, 类别: '数码', 销售额: null }, { id: 2, 类别: '数码', 销售额: 0 }] as unknown as RowResponse[]
    const data = buildCategoryDataset(rows, FIELDS, chart({ agg: 'count' }))
    expect(data.series[0].data).toEqual([1])
  })

  it('median 取中位数', () => {
    const rows = [
      { id: 1, 类别: '数码', 销售额: 10 },
      { id: 2, 类别: '数码', 销售额: 20 },
      { id: 3, 类别: '数码', 销售额: 50 },
      { id: 4, 类别: '数码', 销售额: 90 },
    ] as unknown as RowResponse[]
    const data = buildCategoryDataset(rows, FIELDS, chart({ agg: 'median' }))
    expect(data.series[0].data).toEqual([35])
  })
})

describe('其他 Dataset 装配', () => {
  it('pie 过滤 0 值', () => {
    const rows = [
      { id: 1, 类别: 'A', 销售额: 10 },
      { id: 2, 类别: 'B', 销售额: 0 },
    ] as unknown as RowResponse[]
    expect(buildPieDataset(rows, FIELDS, chart({ type: 'pie' })).items).toEqual([{ name: 'A', value: 10 }])
  })

  it('scatter 跳过非数值并保留 rowIds', () => {
    const rows = [
      { id: 1, 数量: 2, 销售额: 100 },
      { id: 2, 数量: null, 销售额: 50 },
      { id: 3, 数量: '3', 销售额: '60' },
    ] as unknown as RowResponse[]
    const data = buildScatterDataset(rows, chart({ type: 'scatter', x: '数量' }))
    expect(data.points).toEqual([[2, 100], [3, 60]])
    expect(data.rowIds).toEqual([1, 3])
  })

  it('scatter 缺 X 字段返回空点集', () => {
    expect(buildScatterDataset(ROWS, chart({ type: 'scatter', x: undefined })).points).toEqual([])
  })

  it('histogram 分箱覆盖所有数值', () => {
    const data = buildHistogramDataset(ROWS, chart({ type: 'histogram', x: undefined }))
    expect(data.bins.reduce((n, b) => n + b.count, 0)).toBe(6)
    expect(data.bins[0].from).toBe(30)
    expect(data.bins[data.bins.length - 1].to).toBe(120)
  })

  it('boxplot 五数概括与离群值', () => {
    const rows = [
      { id: 1, 类别: '数码', 销售额: 30 },
      { id: 2, 类别: '数码', 销售额: 60 },
      { id: 3, 类别: '数码', 销售额: 100 },
      { id: 4, 类别: '数码', 销售额: 500 },
    ] as unknown as RowResponse[]
    const data = buildBoxplotDataset(rows, FIELDS, chart({ type: 'boxplot' }))
    expect(data.categories).toEqual(['数码'])
    // 线性插值分位数（R-7）：[30,60,100,500] → q1=52.5 / q3=200
    expect(data.boxes[0]).toEqual([30, 52.5, 80, 200, 500])
    expect(data.outliers).toEqual([[0, 500]])
  })

  it('radar 指标上限与多边形，支持按 series 拆分', () => {
    const data = buildRadarDataset(ROWS, FIELDS, chart({ type: 'radar', y: ['销售额', '数量'] }))
    expect(data.indicators.map((i) => i.name)).toEqual(['销售额', '数量'])
    expect(data.indicators[0].max).toBe(Math.ceil(200 * 1.1))
    const split = buildRadarDataset(ROWS, FIELDS, chart({ type: 'radar', series: '日期' }))
    expect(split.series.length).toBeGreaterThan(3)
  })

  it('funnel 默认按数值降序，支持 top_n 与维度升序', () => {
    expect(buildFunnelDataset(ROWS, FIELDS, chart({ type: 'funnel' })).items.map((i) => i.value))
      .toEqual([200, 120, 90])
    expect(buildFunnelDataset(ROWS, FIELDS, chart({ type: 'funnel', top_n: 2 })).items).toHaveLength(2)
    expect(buildFunnelDataset(ROWS, FIELDS, chart({ type: 'funnel', sort: 'x_asc' })).items.map((i) => i.name))
      .toEqual(['家电', '食品', '数码'])
  })

  it('gauge 目标值缺省取 1.2 倍', () => {
    const data = buildGaugeDataset(ROWS, chart({ type: 'gauge', target: undefined }))
    expect(data.value).toBe(410)
    expect(data.target).toBe(492)
    expect(buildGaugeDataset(ROWS, chart({ type: 'gauge', target: 500 })).target).toBe(500)
  })

  it('heatmap 输出 x × y 矩阵与最大值', () => {
    const data = buildHeatmapDataset(ROWS, FIELDS, chart({ type: 'heatmap', series: '日期' }))
    expect(data.x).toEqual(['家电', '食品', '数码'])
    expect(data.y).toEqual(['2026-01', '2026-02', '2026-03'])
    expect(data.values).toHaveLength(9)
    expect(data.max).toBe(130)
  })

  it('treemap 父子节点按数值降序', () => {
    const data = buildTreemapDataset(ROWS, FIELDS, chart({ type: 'treemap', series: '日期' }))
    expect(data.nodes[0].name).toBe('数码')
    expect(data.nodes[0].value).toBe(200)
    expect(data.nodes[0].children?.[0].name).toBe('2026-01')
  })

  it('buildDashboardDataset 按 type 分派 14 类', () => {
    const types: DashboardChartType[] = [
      'bar', 'line', 'area', 'stack', 'combo', 'pie', 'scatter',
      'histogram', 'boxplot', 'radar', 'funnel', 'gauge', 'heatmap', 'treemap',
    ]
    const kinds = types.map((type) => buildDashboardDataset(ROWS, FIELDS, chart({ type, series: '日期' })).kind)
    expect(kinds).toEqual([
      'category', 'category', 'category', 'category', 'category', 'pie', 'scatter',
      'histogram', 'boxplot', 'radar', 'funnel', 'gauge', 'heatmap', 'treemap',
    ])
  })
})

/** dashboard 图表数据装配（ADR 0023 P2 客户端口径）.
 *
 * 输入：行集 + 字段定义 + `DashboardChart` 配置；输出统一 `Dataset`。
 * 与后端 dashboard 聚合端点保持同构（I3），`ChartWidget` 只消费 Dataset。
 */

import type { Field, RowResponse } from '@/api'
import { extractNumbers, histogramBins, toNumber } from '../../chartBoard'
import {
  UNGROUPED_LABEL,
  axisKeyForRow,
  isDateAxis,
  sortAxisKeys,
} from '../../matrixBoard'
import type { DashboardAggregation, DashboardChart } from '../dashboardModel'
import type {
  BoxplotDataset,
  CategoryDataset,
  Dataset,
  FunnelDataset,
  GaugeDataset,
  HeatmapDataset,
  HistogramDataset,
  PieDataset,
  RadarDataset,
  ScatterDataset,
  TreemapDataset,
} from './types'

const SINGLE = '__single__'

function isBlank(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim() === '')
}

/** 维度键：日期按月分桶，空值归「未分组」（与矩阵视图同口径） */
function dimKey(row: RowResponse, fieldDef: Field | undefined, dateGranularity: 'month' = 'month'): string {
  return axisKeyForRow(row, fieldDef, dateGranularity) || UNGROUPED_LABEL
}

/** 桶内聚合；count 只计非空值（对齐 SQL COUNT(col)） */
function aggregate(raw: unknown[], agg: DashboardAggregation): number | null {
  if (!raw.length) return null
  if (agg === 'count') return raw.reduce<number>((n, v) => n + (isBlank(v) ? 0 : 1), 0)
  const nums: number[] = []
  for (const v of raw) {
    const n = toNumber(v)
    if (n !== null) nums.push(n)
  }
  if (!nums.length) return null
  switch (agg) {
    case 'sum': return nums.reduce((a, b) => a + b, 0)
    case 'avg': return nums.reduce((a, b) => a + b, 0) / nums.length
    case 'min': return Math.min(...nums)
    case 'max': return Math.max(...nums)
    case 'median': {
      const sorted = [...nums].sort((a, b) => a - b)
      const mid = Math.floor(sorted.length / 2)
      return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
    }
    default: return null
  }
}

interface Buckets {
  categories: string[]
  /** seriesName → 每个 category 的原始值集合 */
  series: Map<string, Map<string, unknown[]>>
}

/** 按维度 × 系列收集原始值（多度量时逐 y 建桶，series 名带度量前缀） */
function collect(rows: RowResponse[], fields: Field[], cfg: DashboardChart): Buckets {
  const dimDef = fields.find((f) => f.name === cfg.x)
  const seriesDef = fields.find((f) => f.name === cfg.series)
  const series = new Map<string, Map<string, unknown[]>>()
  const categories = new Set<string>()
  for (const row of rows) {
    const cat = dimKey(row, dimDef)
    categories.add(cat)
    const seriesValue = cfg.series ? dimKey(row, seriesDef) : SINGLE
    cfg.y.forEach((field) => {
      let seriesName: string
      if (cfg.y.length > 1) {
        seriesName = cfg.series ? `${field} · ${seriesValue}` : field
      } else {
        seriesName = cfg.series ? seriesValue : field
      }
      let bySeries = series.get(seriesName)
      if (!bySeries) {
        bySeries = new Map()
        series.set(seriesName, bySeries)
      }
      const arr = bySeries.get(cat)
      if (arr) arr.push(row[field])
      else bySeries.set(cat, [row[field]])
    })
  }
  return { categories: [...categories], series }
}

/** 排序 + TopN（其余并「其他」）；asc/desc 为 P0 兼容值（等价 y）」 */
function finalizeCategories(
  dataset: CategoryDataset,
  cfg: DashboardChart,
  dateAxis: boolean,
): CategoryDataset {
  let categories = [...dataset.categories]
  const sort = cfg.sort
  if (sort !== 'none') {
    const byY = sort === 'asc' || sort === 'desc' || sort === 'y_asc' || sort === 'y_desc'
    const desc = sort === 'desc' || sort === 'y_desc' || sort === 'x_desc'
    const metric = (cat: string): number =>
      dataset.series.reduce((sum, s) => sum + (s.data[dataset.categories.indexOf(cat)] ?? 0), 0)
    categories.sort((a, b) => {
      const c = byY ? metric(a) - metric(b) : a.localeCompare(b, 'zh-CN')
      return desc ? -c : c
    })
  }
  if (!dateAxis && cfg.sort === 'none') categories = sortAxisKeys(categories, false)
  if (dateAxis && cfg.sort === 'none') categories = sortAxisKeys(categories, true)

  if (cfg.top_n && categories.length > cfg.top_n) {
    const keep = categories.slice(0, cfg.top_n)
    const rest = categories.slice(cfg.top_n)
    const other = dataset.series.map((s) => ({
      name: s.name,
      data: [rest.reduce((sum, cat) => sum + (s.data[dataset.categories.indexOf(cat)] ?? 0), 0)],
    }))
    categories = [...keep, '其他']
    dataset = {
      kind: 'category',
      categories,
      series: dataset.series.map((s, i) => ({
        name: s.name,
        data: [
          ...keep.map((cat) => s.data[dataset.categories.indexOf(cat)] ?? null),
          other[i].data[0],
        ],
      })),
    }
  } else {
    dataset = {
      kind: 'category',
      categories,
      series: dataset.series.map((s) => ({
        name: s.name,
        data: categories.map((cat) => s.data[dataset.categories.indexOf(cat)] ?? null),
      })),
    }
  }
  if (cfg.stack === 'percent') {
    const total = categories.map((_, ci) =>
      dataset.series.reduce((sum, s) => sum + (s.data[ci] ?? 0), 0),
    )
    dataset = {
      ...dataset,
      series: dataset.series.map((s) => ({
        name: s.name,
        data: s.data.map((v, ci) => (total[ci] > 0 && v !== null ? (v / total[ci]) * 100 : null)),
      })),
    }
  }
  return dataset
}

/** bar/line/area/stack/combo：类目 ×（多）度量聚合 */
export function buildCategoryDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): CategoryDataset {
  const dimDef = fields.find((f) => f.name === cfg.x)
  const { categories, series } = collect(rows, fields, cfg)
  const base: CategoryDataset = {
    kind: 'category',
    categories,
    series: [...series.entries()].map(([name, byCat]) => ({
      name,
      data: categories.map((cat) => aggregate(byCat.get(cat) ?? [], cfg.agg)),
    })),
  }
  const sorted = finalizeCategories(base, cfg, isDateAxis(dimDef))
  // 送进 finalize 前的 series.data 已按原 categories 顺序；finalize 用 indexOf 重排
  return sorted
}

export function buildPieDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): PieDataset {
  const cat = buildCategoryDataset(rows, fields, cfg)
  const first = cat.series[0]
  return {
    kind: 'pie',
    items: cat.categories.map((name, i) => ({ name, value: first?.data[i] ?? 0 }))
      .filter((it) => it.value !== 0),
  }
}

export function buildScatterDataset(rows: RowResponse[], cfg: DashboardChart): ScatterDataset {
  const points: Array<[number, number]> = []
  const rowIds: Array<RowResponse['id']> = []
  if (!cfg.x) return { kind: 'scatter', points, rowIds }
  for (const r of rows) {
    const x = toNumber(r[cfg.x])
    const y = toNumber(r[cfg.y[0]])
    if (x === null || y === null) continue
    points.push([x, y])
    rowIds.push(r.id)
  }
  return { kind: 'scatter', points, rowIds }
}

export function buildHistogramDataset(rows: RowResponse[], cfg: DashboardChart): HistogramDataset {
  return { kind: 'histogram', bins: histogramBins(extractNumbers(rows, cfg.y[0])) }
}

export function buildBoxplotDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): BoxplotDataset {
  const dimDef = fields.find((f) => f.name === cfg.x)
  const buckets = new Map<string, number[]>()
  for (const r of rows) {
    const key = dimKey(r, dimDef)
    const v = toNumber(r[cfg.y[0]])
    if (v === null) continue
    const arr = buckets.get(key)
    if (arr) arr.push(v)
    else buckets.set(key, [v])
  }
  const categories = sortAxisKeys([...buckets.keys()], isDateAxis(dimDef))
  const boxes: number[][] = []
  const outliers: Array<[number, number]> = []
  categories.forEach((cat, ci) => {
    const sorted = [...(buckets.get(cat) ?? [])].sort((a, b) => a - b)
    if (!sorted.length) return
    const quantile = (q: number): number => {
      const pos = (sorted.length - 1) * q
      const low = Math.floor(pos)
      const high = Math.ceil(pos)
      return low === high ? sorted[low] : sorted[low] + (sorted[high] - sorted[low]) * (pos - low)
    }
    const q1 = quantile(0.25)
    const med = quantile(0.5)
    const q3 = quantile(0.75)
    boxes.push([sorted[0], q1, med, q3, sorted[sorted.length - 1]])
    const lo = q1 - 1.5 * (q3 - q1)
    const hi = q3 + 1.5 * (q3 - q1)
    for (const v of sorted) if (v < lo || v > hi) outliers.push([ci, v])
  })
  return { kind: 'boxplot', categories, boxes, outliers }
}

/** 雷达：指标 = y[]，多边形 = x 类目（可选再按 series 拆分） */
export function buildRadarDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): RadarDataset {
  const dimDef = fields.find((f) => f.name === cfg.x)
  const seriesDef = fields.find((f) => f.name === cfg.series)
  const polygons = new Map<string, RowResponse[]>()
  for (const r of rows) {
    const cat = dimKey(r, dimDef)
    const key = cfg.series ? `${cat} · ${dimKey(r, seriesDef)}` : cat
    const arr = polygons.get(key)
    if (arr) arr.push(r)
    else polygons.set(key, [r])
  }
  const names = sortAxisKeys([...polygons.keys()], false)
  const raw = names.map((name) => {
    const group = polygons.get(name) ?? []
    return {
      name,
      values: cfg.y.map((field) => aggregate(group.map((r) => r[field]), cfg.agg) ?? 0),
    }
  })
  const indicators = cfg.y.map((name, i) => {
    const max = Math.max(1, ...raw.map((s) => s.values[i]))
    return { name, max: Math.ceil(max * 1.1) }
  })
  return { kind: 'radar', indicators, series: raw }
}

export function buildFunnelDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): FunnelDataset {
  const cat = buildCategoryDataset(rows, fields, { ...cfg, stack: 'none' })
  const first = cat.series[0]
  const items = cat.categories.map((name, i) => ({ name, value: first?.data[i] ?? 0 }))
  const sort = cfg.sort === 'none' ? 'y_desc' : cfg.sort
  const desc = sort === 'desc' || sort === 'y_desc' || sort === 'x_desc'
  items.sort((a, b) => {
    const c = sort === 'x_asc' || sort === 'x_desc'
      ? a.name.localeCompare(b.name, 'zh-CN')
      : a.value - b.value
    return desc ? -c : c
  })
  const sliced = cfg.top_n ? items.slice(0, cfg.top_n) : items
  return { kind: 'funnel', items: sliced }
}

export function buildGaugeDataset(rows: RowResponse[], cfg: DashboardChart): GaugeDataset {
  const value = aggregate(rows.map((r) => r[cfg.y[0]]), cfg.agg)
  const target = cfg.target ?? (value !== null ? Math.max(1, Math.ceil(value * 1.2)) : undefined)
  return { kind: 'gauge', name: cfg.y[0], value, target }
}

/** 热力：x × series → 聚合值矩阵 */
export function buildHeatmapDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): HeatmapDataset {
  const xDef = fields.find((f) => f.name === cfg.x)
  const yDef = fields.find((f) => f.name === cfg.series)
  const cells = new Map<string, Map<string, unknown[]>>()
  for (const r of rows) {
    const xKey = dimKey(r, xDef)
    const yKey = dimKey(r, yDef)
    let byY = cells.get(xKey)
    if (!byY) {
      byY = new Map()
      cells.set(xKey, byY)
    }
    const arr = byY.get(yKey)
    if (arr) arr.push(r[cfg.y[0]])
    else byY.set(yKey, [r[cfg.y[0]]])
  }
  const x = sortAxisKeys([...cells.keys()], isDateAxis(xDef))
  const yKeys = new Set<string>()
  for (const byY of cells.values()) for (const k of byY.keys()) yKeys.add(k)
  const y = sortAxisKeys([...yKeys], isDateAxis(yDef))
  const values: Array<[number, number, number]> = []
  let max = 0
  x.forEach((xv, xi) => {
    y.forEach((yv, yi) => {
      const v = aggregate(cells.get(xv)?.get(yv) ?? [], cfg.agg) ?? 0
      values.push([xi, yi, v])
      max = Math.max(max, v)
    })
  })
  return { kind: 'heatmap', x, y, values, max: max || 1 }
}

/** 矩形树：x 类目为父节点，series 为子节点 */
export function buildTreemapDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): TreemapDataset {
  const xDef = fields.find((f) => f.name === cfg.x)
  const sDef = fields.find((f) => f.name === cfg.series)
  const children = new Map<string, Map<string, unknown[]>>()
  for (const r of rows) {
    const parent = dimKey(r, xDef)
    const child = dimKey(r, sDef)
    let byChild = children.get(parent)
    if (!byChild) {
      byChild = new Map()
      children.set(parent, byChild)
    }
    const arr = byChild.get(child)
    if (arr) arr.push(r[cfg.y[0]])
    else byChild.set(child, [r[cfg.y[0]]])
  }
  const nodes = [...children.entries()].map(([name, byChild]) => {
    const items = [...byChild.entries()].map(([childName, vals]) => ({
      name: childName,
      value: aggregate(vals, cfg.agg) ?? 0,
    }))
    return {
      name,
      value: items.reduce((sum, it) => sum + it.value, 0),
      children: items,
    }
  })
  return { kind: 'treemap', nodes: nodes.sort((a, b) => (b.value ?? 0) - (a.value ?? 0)) }
}

/** 统一入口：按 chart.type 装配 Dataset */
export function buildDashboardDataset(rows: RowResponse[], fields: Field[], cfg: DashboardChart): Dataset {
  switch (cfg.type) {
    case 'pie': return buildPieDataset(rows, fields, cfg)
    case 'scatter': return buildScatterDataset(rows, cfg)
    case 'histogram': return buildHistogramDataset(rows, cfg)
    case 'boxplot': return buildBoxplotDataset(rows, fields, cfg)
    case 'radar': return buildRadarDataset(rows, fields, cfg)
    case 'funnel': return buildFunnelDataset(rows, fields, cfg)
    case 'gauge': return buildGaugeDataset(rows, cfg)
    case 'heatmap': return buildHeatmapDataset(rows, fields, cfg)
    case 'treemap': return buildTreemapDataset(rows, fields, cfg)
    case 'bar':
    case 'line':
    case 'area':
    case 'stack':
    case 'combo':
    default: return buildCategoryDataset(rows, fields, cfg)
  }
}

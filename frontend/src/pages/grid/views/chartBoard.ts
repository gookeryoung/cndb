/** 图表视图纯逻辑层 — 聚合/分箱/统计与 UI 解耦，可独立单测.
 *
 * 职责（设计契约见 .trae/designs/chart-view.md）：
 * - buildChartData：行集合按 chart_type 变换为 ECharts 可消费的数据结构
 *   （维度聚合 / 多系列 / 日期分桶复用 matrixBoard，散点取双数值列，直方图分箱，箱线图五数概括）
 * - histogramBins：三种分箱策略（square-root / Sturges / Freedman-Diaconis，IQR=0 回退 Sturges）
 * - computeStats：描述统计（样本标准差 n-1、线性插值分位、IQR 离群值法）
 * - pearson / olsLine：散点图相关与回归（可复用于后续报表/聚合栏）
 *
 * 统计口径：
 * - 空值/非数值统一剔除后再聚合（count 同样只计有效值，对齐 SQL COUNT(col) 语义）
 * - 分位数采用线性插值（R-7，simple-statistics 默认）
 * - 众数取频率最高值之一（多众数时取首个，顺序遵循 simple-statistics mode）
 */

import type { Field, RowResponse } from '@/api'
import {
  linearRegression,
  max as ssMax,
  mean,
  min as ssMin,
  mode,
  quantileSorted,
  sampleCorrelation,
  sampleSkewness,
  sampleStandardDeviation,
  sum as ssSum,
} from 'simple-statistics'
import {
  UNGROUPED_LABEL,
  axisKeyForRow,
  isDateAxis,
  sortAxisKeys,
  type MatrixDateGranularity,
} from './matrixBoard'

// ── 类型与常量 ────────────────────────────────────────

/** 图表类型 */
export type ChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'histogram' | 'boxplot'

/** 聚合方式 */
export type ChartAggregation = 'sum' | 'avg' | 'count' | 'min' | 'max'

/** 直方图分箱策略 */
export type BinPolicy = 'auto' | 'sturges' | 'freedman-diaconis'

/** chart 视图 view_options 解析后的配置（resolveOpts 产物） */
export interface ChartConfig {
  chart_type: ChartType
  dimension_field?: string
  measure_field?: string
  x_field?: string
  y_field?: string
  group_field?: string
  aggregation?: ChartAggregation
  date_granularity?: MatrixDateGranularity
  bin_policy?: BinPolicy
  /** 散点 OLS 趋势线开关（默认 false） */
  show_trend_line?: boolean
  /** 统计面板开关（默认 true） */
  show_stats_panel?: boolean
}

/** 无 group_field 时的单系列名 */
export const SINGLE_SERIES = '__single__'

// ── 数值提取 ──────────────────────────────────────────

/** 行值 → 有限数值；null/undefined/空串/非数字串/NaN/Infinity 返回 null */
export function toNumber(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** 从行集合提取某字段的有效数值数组（保持行序，空值/非数值剔除） */
export function extractNumbers(rows: RowResponse[], fieldName: string | undefined): number[] {
  if (!fieldName) return []
  const out: number[] = []
  for (const r of rows) {
    const n = toNumber(r[fieldName])
    if (n !== null) out.push(n)
  }
  return out
}

// ── 图表数据变换 ──────────────────────────────────────

/** bar/line 维度聚合数据（多系列按 group_field 对齐；无值桶为 null，不虚构 0） */
export interface CategoryChartData {
  kind: 'category'
  categories: string[]
  series: Array<{ name: string; data: Array<number | null> }>
}

/** pie 数据 */
export interface PieChartData {
  kind: 'pie'
  items: Array<{ name: string; value: number }>
}

/** scatter 数据（points 与 rowIds 平行，点击散点可定位行） */
export interface ScatterChartData {
  kind: 'scatter'
  points: Array<[number, number]>
  rowIds: Array<RowResponse['id']>
}

/** histogram 数据 */
export interface HistogramChartData {
  kind: 'histogram'
  bins: HistogramBin[]
}

/** boxplot 数据（boxes 为 [min,Q1,median,Q3,max]；outliers 为 [类目索引, 值]） */
export interface BoxplotChartData {
  kind: 'boxplot'
  categories: string[]
  boxes: Array<number[]>
  outliers: Array<[number, number]>
}

export type ChartData =
  | CategoryChartData
  | PieChartData
  | ScatterChartData
  | HistogramChartData
  | BoxplotChartData

/** 按聚合方式归并桶内数值 */
function aggregateValues(values: number[], agg: ChartAggregation): number {
  switch (agg) {
    case 'avg': return mean(values)
    case 'count': return values.length
    case 'min': return ssMin(values)
    case 'max': return ssMax(values)
    case 'sum':
    default: return ssSum(values)
  }
}

/** 维度归桶公共骨架：dimKey → seriesKey → 数值列表（空维度归「未分组」；空值行剔除） */
function bucketByDimension(
  rows: RowResponse[],
  fields: Field[],
  cfg: ChartConfig,
  withGroup: boolean,
): { buckets: Map<string, Map<string, number[]>> } {
  const dimDef = fields.find((f) => f.name === cfg.dimension_field)
  const groupDef = fields.find((f) => f.name === cfg.group_field)
  const granularity = cfg.date_granularity ?? 'month'
  const buckets = new Map<string, Map<string, number[]>>()
  for (const r of rows) {
    const dimKey = axisKeyForRow(r, dimDef, granularity) || UNGROUPED_LABEL
    const seriesKey = withGroup
      ? (axisKeyForRow(r, groupDef, granularity) || UNGROUPED_LABEL)
      : SINGLE_SERIES
    const v = toNumber(cfg.measure_field ? r[cfg.measure_field] : undefined)
    if (v === null) continue
    let series = buckets.get(dimKey)
    if (!series) {
      series = new Map()
      buckets.set(dimKey, series)
    }
    const arr = series.get(seriesKey)
    if (arr) arr.push(v)
    else series.set(seriesKey, [v])
  }
  return { buckets }
}

/** bar/line：维度 × 度量聚合，group_field 拆多系列 */
function buildCategoryData(rows: RowResponse[], fields: Field[], cfg: ChartConfig): CategoryChartData {
  const dimDef = fields.find((f) => f.name === cfg.dimension_field)
  const agg = cfg.aggregation ?? 'sum'
  const hasGroup = !!cfg.group_field
  const { buckets } = bucketByDimension(rows, fields, cfg, hasGroup)

  const categories = sortAxisKeys([...buckets.keys()], isDateAxis(dimDef))
  if (!hasGroup) {
    return {
      kind: 'category',
      categories,
      series: [{
        name: cfg.measure_field ?? '',
        data: categories.map((ck) => {
          const vals = buckets.get(ck)?.get(SINGLE_SERIES)
          return vals ? aggregateValues(vals, agg) : null
        }),
      }],
    }
  }
  const seriesKeys = new Set<string>()
  for (const series of buckets.values()) {
    for (const sk of series.keys()) seriesKeys.add(sk)
  }
  const sortedSeriesKeys = sortAxisKeys([...seriesKeys], false)
  return {
    kind: 'category',
    categories,
    series: sortedSeriesKeys.map((sk) => ({
      name: sk,
      data: categories.map((ck) => {
        const vals = buckets.get(ck)?.get(sk)
        return vals ? aggregateValues(vals, agg) : null
      }),
    })),
  }
}

/** pie：维度聚合为扇区 */
function buildPieData(rows: RowResponse[], fields: Field[], cfg: ChartConfig): PieChartData {
  const dimDef = fields.find((f) => f.name === cfg.dimension_field)
  const agg = cfg.aggregation ?? 'sum'
  const { buckets } = bucketByDimension(rows, fields, cfg, false)
  const categories = sortAxisKeys([...buckets.keys()], isDateAxis(dimDef))
  return {
    kind: 'pie',
    items: categories.map((ck) => {
      const vals = buckets.get(ck)?.get(SINGLE_SERIES)
      return { name: ck, value: vals ? aggregateValues(vals, agg) : 0 }
    }),
  }
}

/** scatter：双数值列取点（任一无效则整行剔除），保留行 id 供点击定位 */
function buildScatterData(rows: RowResponse[], cfg: ChartConfig): ScatterChartData {
  const points: Array<[number, number]> = []
  const rowIds: Array<RowResponse['id']> = []
  if (!cfg.x_field || !cfg.y_field) return { kind: 'scatter', points, rowIds }
  for (const r of rows) {
    const x = toNumber(r[cfg.x_field])
    const y = toNumber(r[cfg.y_field])
    if (x === null || y === null) continue
    points.push([x, y])
    rowIds.push(r.id)
  }
  return { kind: 'scatter', points, rowIds }
}

/** boxplot：维度分组五数概括 + IQR 离群点 */
function buildBoxplotData(rows: RowResponse[], fields: Field[], cfg: ChartConfig): BoxplotChartData {
  const dimDef = fields.find((f) => f.name === cfg.dimension_field)
  const granularity = cfg.date_granularity ?? 'month'
  const buckets = new Map<string, number[]>()
  for (const r of rows) {
    const dimKey = axisKeyForRow(r, dimDef, granularity) || UNGROUPED_LABEL
    const v = toNumber(cfg.measure_field ? r[cfg.measure_field] : undefined)
    if (v === null) continue
    const arr = buckets.get(dimKey)
    if (arr) arr.push(v)
    else buckets.set(dimKey, [v])
  }
  const categories = sortAxisKeys([...buckets.keys()], isDateAxis(dimDef))
  const boxes: Array<number[]> = []
  const outliers: Array<[number, number]> = []
  categories.forEach((ck, ci) => {
    const vals = buckets.get(ck) ?? []
    const sorted = [...vals].sort((a, b) => a - b)
    const q1 = quantileSorted(sorted, 0.25)
    const med = quantileSorted(sorted, 0.5)
    const q3 = quantileSorted(sorted, 0.75)
    boxes.push([sorted[0], q1, med, q3, sorted[sorted.length - 1]])
    const lo = q1 - 1.5 * (q3 - q1)
    const hi = q3 + 1.5 * (q3 - q1)
    for (const v of vals) {
      if (v < lo || v > hi) outliers.push([ci, v])
    }
  })
  return { kind: 'boxplot', categories, boxes, outliers }
}

/** 统一入口：按 chart_type 把行集合变换为图表数据（调用前须已配置必填字段） */
export function buildChartData(rows: RowResponse[], fields: Field[], cfg: ChartConfig): ChartData {
  switch (cfg.chart_type) {
    case 'pie': return buildPieData(rows, fields, cfg)
    case 'scatter': return buildScatterData(rows, cfg)
    case 'histogram': return { kind: 'histogram', bins: histogramBins(extractNumbers(rows, cfg.measure_field), cfg.bin_policy) }
    case 'boxplot': return buildBoxplotData(rows, fields, cfg)
    case 'bar':
    case 'line':
    default: return buildCategoryData(rows, fields, cfg)
  }
}

// ── 直方图分箱 ────────────────────────────────────────

/** 单个分箱 */
export interface HistogramBin {
  /** 区间标签（from~to） */
  label: string
  count: number
  from: number
  to: number
}

/** 分箱数绝对上限（防 FD 在 IQR 极小时产生海量窄箱拖垮渲染） */
const MAX_BIN_COUNT = 512

/** 数值显示：整数原样，否则 6 位有效数字去尾零 */
function fmtNum(v: number): string {
  if (Number.isInteger(v)) return String(v)
  return String(parseFloat(v.toPrecision(6)))
}

/** Sturges 分箱数：ceil(log2(n) + 1) */
function sturgesBins(n: number): number {
  return Math.ceil(Math.log2(n) + 1)
}

/** 按策略计算分箱并计数.
 *
 * - auto：平方根法 ceil(sqrt(n))
 * - sturges：ceil(log2(n) + 1)
 * - freedman-diaconis：ceil((max-min) / (2·IQR/∛n))；IQR=0 退化时回退 Sturges
 * - 全部值相同 / 单元素 → 单箱；binCount 收敛到 [1, min(n, 512)]
 * - 计数区间为 [from, to)，末箱闭区间含 max
 */
export function histogramBins(values: number[], policy: BinPolicy = 'auto'): HistogramBin[] {
  const n = values.length
  if (n === 0) return []
  const min = ssMin(values)
  const max = ssMax(values)
  if (n === 1 || min === max) {
    return [{ label: `${fmtNum(min)}~${fmtNum(max)}`, count: n, from: min, to: max }]
  }

  let binCount: number
  if (policy === 'sturges') {
    binCount = sturgesBins(n)
  } else if (policy === 'freedman-diaconis') {
    const sorted = [...values].sort((a, b) => a - b)
    const iqr = quantileSorted(sorted, 0.75) - quantileSorted(sorted, 0.25)
    binCount = iqr > 0 ? Math.ceil((max - min) / ((2 * iqr) / Math.cbrt(n))) : sturgesBins(n)
  } else {
    binCount = Math.ceil(Math.sqrt(n))
  }
  binCount = Math.max(1, Math.min(binCount, n, MAX_BIN_COUNT))

  const width = (max - min) / binCount
  const bins: HistogramBin[] = []
  for (let i = 0; i < binCount; i++) {
    const from = min + i * width
    const to = i === binCount - 1 ? max : min + (i + 1) * width
    const count = values.reduce((acc, v) => {
      const inBin = i === binCount - 1 ? (v >= from && v <= to) : (v >= from && v < to)
      return acc + (inBin ? 1 : 0)
    }, 0)
    bins.push({ label: `${fmtNum(from)}~${fmtNum(to)}`, count, from, to })
  }
  return bins
}

// ── 描述统计 ──────────────────────────────────────────

/** 描述统计结果（无效口径的字段为 null 而非 NaN，UI 据此隐藏） */
export interface StatsResult {
  count: number
  sum: number
  mean: number
  median: number
  /** 众数（多众数取首个；理论上有值必存在） */
  mode: number | null
  /** 样本标准差（n-1）；n < 2 时 null */
  std: number | null
  min: number
  max: number
  range: number
  p25: number
  p75: number
  iqr: number
  /** 样本偏度；n < 3 时 null */
  skewness: number | null
  /** IQR 法离群值个数（< Q1-1.5·IQR 或 > Q3+1.5·IQR） */
  outlierCount: number
}

/** 计算描述统计（空数组返回 null） */
export function computeStats(values: number[]): StatsResult | null {
  const n = values.length
  if (n === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const sumV = ssSum(values)
  const meanV = mean(values)
  const p25 = quantileSorted(sorted, 0.25)
  const p75 = quantileSorted(sorted, 0.75)
  const iqr = p75 - p25
  const minV = sorted[0]
  const maxV = sorted[n - 1]
  const modes = mode(values)  // simple-statistics v7：返回单个众数（多众数取其一）
  const lo = p25 - 1.5 * iqr
  const hi = p75 + 1.5 * iqr
  return {
    count: n,
    sum: sumV,
    mean: meanV,
    median: quantileSorted(sorted, 0.5),
    mode: modes,
    std: n >= 2 ? sampleStandardDeviation(values) : null,
    min: minV,
    max: maxV,
    range: maxV - minV,
    p25,
    p75,
    iqr,
    skewness: n >= 3 ? sampleSkewness(values) : null,
    outlierCount: values.reduce((acc, v) => acc + (v < lo || v > hi ? 1 : 0), 0),
  }
}

// ── 相关与回归 ────────────────────────────────────────

/** Pearson 相关系数；n < 2 或某轴恒定（分母 0）返回 null */
export function pearson(pairs: Array<[number, number]>): number | null {
  if (pairs.length < 2) return null
  const r = sampleCorrelation(pairs.map((p) => p[0]), pairs.map((p) => p[1]))
  return Number.isFinite(r) ? r : null
}

/** OLS 最小二乘拟合结果 */
export interface OlsLine {
  slope: number
  intercept: number
  /** Pearson r（可显示相关系数） */
  r: number | null
  /** 决定系数 R² = r²；r 为 null 时 null */
  r2: number | null
}

/** OLS 线性拟合；n < 2 或 X 恒定（奇异）返回 null */
export function olsLine(pairs: Array<[number, number]>): OlsLine | null {
  if (pairs.length < 2) return null
  const { m, b } = linearRegression(pairs)
  if (!Number.isFinite(m) || !Number.isFinite(b)) return null
  const r = pearson(pairs)
  return { slope: m, intercept: b, r, r2: r !== null ? r * r : null }
}

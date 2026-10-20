/** K 线视图纯逻辑层 — 行内序列解析 / 周期重采样 / 均线 / 图表 option 装配，与 UI 解耦可独立单测.
 *
 * 数据口径：
 * - 行内 JSON 列约定为 `[{date,open,close,high,low,volume,amount,...}, ...]`，按日期升序、日期唯一；
 * - 解析容忍字符串/数组两种物理形态、常见别名键（date|trade_date|交易日…）与数值字符串，
 *   无效行（缺日期或 OHLC 非数值）整行剔除，同一日期后出现的行覆盖先出现的行；
 * - 周/月线优先取专用 JSON 列，缺失时由日线「同复权口径」派生（open 首日、close 末日、
 *   high max、low min、volume/amount/turnover sum，涨跌幅按周期首开/末收重算），
 *   不静默混用其它复权口径（不复权列缺失时不拿前复权冒充）；
 * - 均线窗口内出现空值或样本不足时返回 null（不插值），与常见行情软件口径一致。
 */

import type { RowResponse } from '@/api'
import { toNumber } from './chartBoard'

// ── 类型与常量 ────────────────────────────────────────

/** K 线周期 */
export type KlinePeriod = 'day' | 'week' | 'month'

/** 复权口径 */
export type KlineAdjust = 'qfq' | 'hfq' | 'none'

/** 规范化后的单根 K 线（数值字段空值统一为 null，UI 据此显示占位） */
export interface KlinePoint {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number | null
  amount: number | null
  /** 振幅（百分数） */
  amplitude: number | null
  /** 涨跌幅（百分数，5.2 表示 5.2%） */
  pct_change: number | null
  /** 涨跌额 */
  change: number | null
  /** 换手率（百分数） */
  turnover: number | null
}

/** kline 视图 view_options 解析后的配置（resolveOpts 产物） */
export interface KlineConfig {
  symbol_field?: string
  name_field?: string
  price_field?: string
  change_pct_field?: string
  volume_field?: string
  amount_field?: string
  date_field?: string
  day_qfq_field?: string
  day_hfq_field?: string
  day_none_field?: string
  week_qfq_field?: string
  month_qfq_field?: string
  default_period?: KlinePeriod
  default_adjust?: KlineAdjust
  show_ma?: boolean
  show_volume?: boolean
  /** 逗号分隔或字符串数组（如 "5,10,20,60"） */
  ma_periods?: string | string[]
}

/** 周期/复权中文标签（空态与工具栏共用） */
export const PERIOD_LABELS: Record<KlinePeriod, string> = {
  day: '日线',
  week: '周线',
  month: '月线',
}

export const ADJUST_LABELS: Record<KlineAdjust, string> = {
  qfq: '前复权',
  hfq: '后复权',
  none: '不复权',
}

/** 周期+复权 → 专用 JSON 列键（未列出的组合没有专用列，由日线派生） */
type SeriesFieldKey =
  | 'day_qfq_field'
  | 'day_hfq_field'
  | 'day_none_field'
  | 'week_qfq_field'
  | 'month_qfq_field'

const DIRECT_SERIES_FIELDS: Record<KlinePeriod, Partial<Record<KlineAdjust, SeriesFieldKey>>> = {
  day: { qfq: 'day_qfq_field', hfq: 'day_hfq_field', none: 'day_none_field' },
  week: { qfq: 'week_qfq_field' },
  month: { qfq: 'month_qfq_field' },
}

/** 默认均线周期 */
export const DEFAULT_MA_PERIODS: readonly number[] = [5, 10, 20, 60]

/** 红涨绿跌（中国/东亚市场惯例；与 ChartView candlestick 同色） */
export const UP_COLOR = '#ef5350'
export const DOWN_COLOR = '#26a69a'

// ── 字段别名 ──────────────────────────────────────────

const DATE_KEYS = ['date', 'trade_date', '交易日', '日期', 'time']
const OPEN_KEYS = ['open', 'o', '开盘', '开盘价']
const CLOSE_KEYS = ['close', 'c', '收盘', '收盘价']
const HIGH_KEYS = ['high', 'h', '最高', '最高价']
const LOW_KEYS = ['low', 'l', '最低', '最低价']
const VOLUME_KEYS = ['volume', 'vol', '成交量']
const AMOUNT_KEYS = ['amount', '成交额']
const AMPLITUDE_KEYS = ['amplitude', '振幅']
const PCT_CHANGE_KEYS = ['pct_change', 'pctChg', 'change_pct', 'pctChange', '涨跌幅']
const CHANGE_KEYS = ['change', 'chg', '涨跌额']
const TURNOVER_KEYS = ['turnover', '换手率']

/** 取对象里第一个有值的别名键 */
function pick(obj: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const k of keys) {
    const v = obj[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return undefined
}

/** 日期归一：支持 YYYY-MM-DD / YYYYMMDD（数字或串）/ 毫秒时间戳；无法识别返回 null */
function normalizeDate(v: unknown): string | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return null
    if (v > 1e11) {
      const d = new Date(v)
      return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10)
    }
    const s = String(Math.trunc(v))
    if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
    return s
  }
  const s = String(v).trim()
  if (!s) return null
  if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
  return s
}

// ── 序列解析 ──────────────────────────────────────────

/** 解析明细（error 非空表示「有原始值但无法解析」，供 UI 走错误态而非空态） */
export interface KlineParseResult {
  points: KlinePoint[]
  error?: string
}

/** 单条原始项 → KlinePoint；缺日期或 OHLC 任一非数值返回 null */
function parsePoint(item: unknown): KlinePoint | null {
  let date: string | null
  let open: number | null
  let close: number | null
  let high: number | null
  let low: number | null
  let volume: number | null = null
  let amount: number | null = null
  let amplitude: number | null = null
  let pctChange: number | null = null
  let change: number | null = null
  let turnover: number | null = null

  if (Array.isArray(item)) {
    // 紧凑元组形态：[date, open, close, high, low, volume?, amount?]
    if (item.length < 5) return null
    date = normalizeDate(item[0])
    open = toNumber(item[1])
    close = toNumber(item[2])
    high = toNumber(item[3])
    low = toNumber(item[4])
    volume = toNumber(item[5])
    amount = toNumber(item[6])
  } else if (item && typeof item === 'object') {
    const o = item as Record<string, unknown>
    date = normalizeDate(pick(o, DATE_KEYS))
    open = toNumber(pick(o, OPEN_KEYS))
    close = toNumber(pick(o, CLOSE_KEYS))
    high = toNumber(pick(o, HIGH_KEYS))
    low = toNumber(pick(o, LOW_KEYS))
    volume = toNumber(pick(o, VOLUME_KEYS))
    amount = toNumber(pick(o, AMOUNT_KEYS))
    amplitude = toNumber(pick(o, AMPLITUDE_KEYS))
    pctChange = toNumber(pick(o, PCT_CHANGE_KEYS))
    change = toNumber(pick(o, CHANGE_KEYS))
    turnover = toNumber(pick(o, TURNOVER_KEYS))
  } else {
    return null
  }

  if (!date || open === null || close === null || high === null || low === null) return null
  return { date, open, close, high, low, volume, amount, amplitude, pct_change: pctChange, change, turnover }
}

/** 行内 JSON 值 → 规范化 K 线序列（升序、按日期去重）.
 *
 * 容错：null/空串/`null` 视为空序列；非法 JSON 或非数组返回空序列并带 error；
 * 数组内无效行剔除（不计为 error）；原始数组非空但无任何有效行时带 error。
 */
export function parseKlineSeriesDetailed(raw: unknown): KlineParseResult {
  if (raw === null || raw === undefined) return { points: [] }
  let data: unknown = raw
  if (typeof raw === 'string') {
    const text = raw.trim()
    if (!text || text === 'null') return { points: [] }
    try {
      data = JSON.parse(text)
    } catch {
      return { points: [], error: 'K 线 JSON 解析失败' }
    }
  }
  if (!Array.isArray(data)) return { points: [], error: 'K 线数据不是数组' }

  const byDate = new Map<string, KlinePoint>()
  for (const item of data) {
    const p = parsePoint(item)
    // 后出现的行覆盖先出现的行（去重口径：以最后一次写入为准）
    if (p) byDate.set(p.date, p)
  }
  const points = [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  if (!points.length && data.length > 0) {
    return { points: [], error: 'K 线数据缺少有效日期或开高低收' }
  }
  return { points }
}

/** 行内 JSON 值 → 规范化 K 线序列（解析失败返回空数组，不抛异常） */
export function parseKlineSeries(raw: unknown): KlinePoint[] {
  return parseKlineSeriesDetailed(raw).points
}

// ── 周期重采样 ────────────────────────────────────────

/** ISO 周键（YYYY-Www）；非 YYYY-MM-DD 前缀的日期回退为原串 */
function isoWeekKey(date: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date)
  if (!m) return date
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])))
  if (Number.isNaN(d.getTime())) return date
  const weekday = d.getUTCDay() || 7 // 周一=1 … 周日=7
  d.setUTCDate(d.getUTCDate() + 4 - weekday) // 移到本周四，归属该周的 ISO 年
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, '0')}`
}

/** 周期分组键：周=ISO 周，月=YYYY-MM */
function periodKey(date: string, period: 'week' | 'month'): string {
  return period === 'month' ? date.slice(0, 7) : isoWeekKey(date)
}

/** 求和；全为空返回 null（不虚构 0） */
function sumOrNull(values: Array<number | null>): number | null {
  let sum = 0
  let seen = false
  for (const v of values) {
    if (v === null || !Number.isFinite(v)) continue
    sum += v
    seen = true
  }
  return seen ? sum : null
}

/** 涨跌幅（百分数）：分母为 0/空返回 null */
function pctOf(numerator: number, denominator: number): number | null {
  if (!Number.isFinite(denominator) || denominator === 0) return null
  return (numerator / denominator) * 100
}

/** 日线 → 周线/月线（open 首日、close 末日、high max、low min、volume/amount/turnover sum）.
 *
 * 聚合点的 date 取该周期最后一个交易日，保证轴标签落在真实交易日；
 * 涨跌幅/涨跌额按「周期首开 → 周期末收」重算，振幅按 (high-low)/open 重算。
 */
export function resampleKline(points: KlinePoint[], period: 'week' | 'month'): KlinePoint[] {
  const buckets = new Map<string, KlinePoint[]>()
  for (const p of points) {
    const key = periodKey(p.date, period)
    const arr = buckets.get(key)
    if (arr) arr.push(p)
    else buckets.set(key, [p])
  }
  const out: KlinePoint[] = []
  for (const group of buckets.values()) {
    let first = group[0]
    let last = group[group.length - 1]
    let high = group[0].high
    let low = group[0].low
    for (const p of group) {
      if (p.date < first.date) first = p
      if (p.date > last.date) last = p
      if (p.high > high) high = p.high
      if (p.low < low) low = p.low
    }
    const open = first.open
    const close = last.close
    out.push({
      date: last.date,
      open,
      close,
      high,
      low,
      volume: sumOrNull(group.map((p) => p.volume)),
      amount: sumOrNull(group.map((p) => p.amount)),
      amplitude: pctOf(high - low, open),
      pct_change: pctOf(close - open, open),
      change: close - open,
      turnover: sumOrNull(group.map((p) => p.turnover)),
    })
  }
  return out.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
}

// ── 均线 ──────────────────────────────────────────────

/** 简单移动平均：窗口内任一为空或样本不足返回 null（不插值） */
export function computeMA(values: Array<number | null>, period: number): Array<number | null> {
  const out: Array<number | null> = values.map(() => null)
  if (!Number.isInteger(period) || period <= 0) return out
  let sum = 0
  let nulls = 0
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v === null || !Number.isFinite(v)) nulls += 1
    else sum += v
    if (i >= period) {
      const old = values[i - period]
      if (old === null || !Number.isFinite(old)) nulls -= 1
      else sum -= old
    }
    if (i >= period - 1 && nulls === 0) out[i] = sum / period
  }
  return out
}

/** 解析 ma_periods 配置（"5,10,20,60" 或数组）→ 去重正整数列表；无有效值时回退默认周期 */
export function parseMaPeriods(raw: unknown): number[] {
  const values = Array.isArray(raw)
    ? raw
    : typeof raw === 'string'
      ? raw.split(',')
      : []
  const out: number[] = []
  for (const v of values) {
    const n = typeof v === 'number' ? v : Number(String(v).trim())
    if (Number.isInteger(n) && n > 0 && n <= 250 && !out.includes(n)) out.push(n)
  }
  return out.length ? out : [...DEFAULT_MA_PERIODS]
}

// ── 序列选择 ──────────────────────────────────────────

/** 序列解析结果（source 标明取数路径，UI 可据此提示「由日线派生」） */
export interface ResolvedKlineSeries {
  points: KlinePoint[]
  /** column=直接取专用列；derived=由日线同复权口径派生；empty=无可用数据 */
  source: 'column' | 'derived' | 'empty'
  /** 实际使用的字段名 */
  field?: string
  /** source='empty' 时的可读原因 */
  message?: string
  /** 原始数据存在但解析失败的错误信息（UI 走错误态） */
  error?: string
}

/** 按周期+复权解析某行的 K 线序列.
 *
 * 顺序：专用列（日线三口径 / 周月前复权）→ 日线同复权口径派生 → 空态（带原因）。
 * 专用列存在但为空/解析失败时仍尝试派生（数据同步未覆盖该周期时回退到日线）。
 */
export function resolveSeries(
  row: RowResponse,
  cfg: KlineConfig,
  period: KlinePeriod,
  adjust: KlineAdjust,
): ResolvedKlineSeries {
  const directKey = DIRECT_SERIES_FIELDS[period][adjust]
  const directField = directKey ? cfg[directKey] : undefined
  const dayField = cfg[DIRECT_SERIES_FIELDS.day[adjust] as SeriesFieldKey]
  const label = `${PERIOD_LABELS[period]}${ADJUST_LABELS[adjust]}`

  let error: string | undefined
  if (directField) {
    const direct = parseKlineSeriesDetailed(row[directField])
    if (direct.points.length) {
      return { points: direct.points, source: 'column', field: directField }
    }
    if (direct.error) error = `${directField}: ${direct.error}`
  }

  if (period !== 'day' && dayField) {
    const daily = parseKlineSeriesDetailed(row[dayField])
    if (daily.points.length) {
      return {
        points: resampleKline(daily.points, period === 'week' ? 'week' : 'month'),
        source: 'derived',
        field: dayField,
      }
    }
    if (daily.error) error = error ?? `${dayField}: ${daily.error}`
  }

  const hasAnyField = !!directField || (period !== 'day' && !!dayField)
  return {
    points: [],
    source: 'empty',
    message: hasAnyField ? `${label}暂无数据` : `未配置${label}字段（视图设置）`,
    error,
  }
}

/** 最新一根 K 线（序列已升序，取末位）；空序列返回 null */
export function latestQuote(points: KlinePoint[]): KlinePoint | null {
  return points.length ? points[points.length - 1] : null
}

// ── 展示格式化 ────────────────────────────────────────

/** 价格显示：空值 —；整数原样；非整数固定两位小数（列对齐与行情软件口径） */
export function formatPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

/** 通用数值显示（均线/振幅/换手率）：空值 —；整数原样；浮点去尾零（默认 6 位有效数字） */
export function formatNumber(v: number | null | undefined, sig = 6): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  if (Number.isInteger(v)) return String(v)
  return String(parseFloat(v.toPrecision(sig)))
}

/** 大手数缩写：≥1 亿 → 亿，≥1 万 → 万，其余保留 6 位有效数字 */
export function compactNumber(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e8) return `${parseFloat((v / 1e8).toPrecision(4))}亿`
  if (abs >= 1e4) return `${parseFloat((v / 1e4).toPrecision(4))}万`
  return String(parseFloat(v.toPrecision(6)))
}

/** 涨跌幅显示（带符号，两位小数） */
export function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

/** 涨跌配色：正红、负绿、空/零中性色 */
export function quoteColor(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return 'var(--cn-text-secondary)'
  return v > 0 ? UP_COLOR : DOWN_COLOR
}

// ── ECharts option 装配 ───────────────────────────────

/** 主题色（由组件读 CSS 变量注入；缺省回退浅色默认值） */
export interface KlineOptionTheme {
  text: string
  secondary: string
  border: string
  bg: string
}

export const DEFAULT_KLINE_THEME: KlineOptionTheme = {
  text: '#1f2937',
  secondary: '#6b7280',
  border: '#e5e7eb',
  bg: '#ffffff',
}

export interface BuildKlineOptionOpts {
  showMa?: boolean
  showVolume?: boolean
  maPeriods?: number[]
  theme?: KlineOptionTheme
  /** dataZoom 初始可见窗口的 K 线根数（默认 120） */
  windowSize?: number
}

/** 均线配色（与红涨绿跌区分，避开红/绿主色） */
const MA_COLORS: readonly string[] = ['#f6bd16', '#5b8ff9', '#945fb9', '#13c2c2', '#fa8c16', '#2f54eb']

/** 按索引取均线颜色 */
export function maColor(index: number): string {
  return MA_COLORS[index % MA_COLORS.length]
}

/** tooltip 行（HTML 片段；数值全为受控格式化结果，无用户原始串注入） */
function tooltipHtml(
  points: KlinePoint[],
  maValues: Array<{ period: number; values: Array<number | null> }>,
  dataIndex: number,
): string {
  const p = dataIndex >= 0 ? points[dataIndex] : undefined
  if (!p) return ''
  const closeColor = p.close >= p.open ? UP_COLOR : DOWN_COLOR
  const lines = [
    `<div style="font-weight:600;margin-bottom:4px">${p.date}</div>`,
    `<div>开盘 ${formatPrice(p.open)}<span style="margin-left:12px">收盘 <span style="color:${closeColor}">${formatPrice(p.close)}</span></span></div>`,
    `<div>最高 ${formatPrice(p.high)}<span style="margin-left:12px">最低 ${formatPrice(p.low)}</span></div>`,
  ]
  if (p.pct_change !== null || p.change !== null) {
    const pct = formatPct(p.pct_change)
    const chg = p.change === null ? '' : `（${p.change > 0 ? '+' : ''}${formatPrice(p.change)}）`
    lines.push(`<div>涨跌幅 <span style="color:${quoteColor(p.pct_change)}">${pct}</span>${chg}</div>`)
  }
  lines.push(`<div>成交量 ${compactNumber(p.volume)}<span style="margin-left:12px">成交额 ${compactNumber(p.amount)}</span></div>`)
  if (p.amplitude !== null || p.turnover !== null) {
    lines.push(`<div>振幅 ${formatNumber(p.amplitude)}%<span style="margin-left:12px">换手率 ${formatNumber(p.turnover)}%</span></div>`)
  }
  maValues.forEach((ma, i) => {
    const v = ma.values[dataIndex] ?? null
    lines.push(`<div><span style="color:${maColor(i)}">MA${ma.period}</span> ${formatPrice(v)}</div>`)
  })
  return lines.join('')
}

/** 装配 ECharts option：双 grid（价格 + 成交量）、MA 叠加、dataZoom 联动、红涨绿跌.
 *
 * - showVolume=false 时退化为单 grid（价格占满高度）；
 * - 成交量柱按当日收盘 vs 开盘着色（红涨绿跌），成交量轴刻度用「万/亿」缩写；
 * - dataZoom（inside + slider）同时作用于两个 xAxis，axisPointer 通过 link 对齐十字线；
 * - tooltip 展示 OHLC / 涨跌幅 / 量额 / 振幅换手 / 各条均线值。
 */
export function buildKlineOption(points: KlinePoint[], opts: BuildKlineOptionOpts = {}): Record<string, unknown> {
  const theme = opts.theme ?? DEFAULT_KLINE_THEME
  const showMa = opts.showMa !== false
  const showVolume = opts.showVolume !== false
  const maPeriods = opts.maPeriods ?? [...DEFAULT_MA_PERIODS]
  const windowSize = Math.max(1, Math.trunc(opts.windowSize ?? 120))

  const categories = points.map((p) => p.date)
  const closes = points.map((p) => p.close)
  const maValues = showMa
    ? maPeriods.map((period) => ({ period, values: computeMA(closes, period) }))
    : []
  const start = points.length > windowSize ? ((points.length - windowSize) / points.length) * 100 : 0
  const xAxisIndex = showVolume ? [0, 1] : [0]

  const axisBase = {
    type: 'category',
    boundaryGap: true,
    axisLine: { lineStyle: { color: theme.border } },
    axisTick: { lineStyle: { color: theme.border } },
    axisLabel: { color: theme.secondary },
    splitLine: { show: false },
  }

  const series: Array<Record<string, unknown>> = [
    {
      name: 'K线',
      type: 'candlestick',
      data: points.map((p) => [p.open, p.close, p.low, p.high]),
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_COLOR,
        borderColor0: DOWN_COLOR,
      },
    },
    ...maValues.map((ma, i) => ({
      name: `MA${ma.period}`,
      type: 'line',
      data: ma.values,
      xAxisIndex: 0,
      yAxisIndex: 0,
      showSymbol: false,
      connectNulls: false,
      smooth: false,
      lineStyle: { width: 1.2, color: maColor(i) },
      itemStyle: { color: maColor(i) },
      z: 3,
    })),
  ]
  if (showVolume) {
    series.push({
      name: '成交量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      barWidth: '60%',
      data: points.map((p) => ({
        value: p.volume,
        itemStyle: { color: p.close >= p.open ? UP_COLOR : DOWN_COLOR },
      })),
    })
  }

  return {
    animation: false,
    legend: showMa
      ? {
          top: 0,
          left: 8,
          itemGap: 10,
          textStyle: { color: theme.secondary },
          data: maValues.map((ma) => `MA${ma.period}`),
        }
      : undefined,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: theme.bg,
      borderColor: theme.border,
      textStyle: { color: theme.text },
      formatter: (rawParams: unknown) => {
        const list = Array.isArray(rawParams) ? rawParams : [rawParams]
        const first = list[0] as { dataIndex?: number } | undefined
        const idx = typeof first?.dataIndex === 'number' ? first.dataIndex : -1
        return tooltipHtml(points, maValues, idx)
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#6b7280' } },
    grid: showVolume
      ? [
          { left: 64, right: 24, top: 32, height: '56%' },
          { left: 64, right: 24, top: '74%', height: '16%' },
        ]
      : [{ left: 64, right: 24, top: 32, bottom: 56 }],
    xAxis: showVolume
      ? [
          { ...axisBase, gridIndex: 0, data: categories, axisLabel: { show: false } },
          { ...axisBase, gridIndex: 1, data: categories },
        ]
      : [{ ...axisBase, gridIndex: 0, data: categories }],
    yAxis: showVolume
      ? [
          {
            type: 'value',
            gridIndex: 0,
            scale: true,
            axisLine: { show: false },
            splitLine: { lineStyle: { color: theme.border } },
            axisLabel: { color: theme.secondary },
          },
          {
            type: 'value',
            gridIndex: 1,
            splitNumber: 2,
            axisLine: { show: false },
            splitLine: { show: false },
            axisLabel: { color: theme.secondary, formatter: (v: number) => compactNumber(v) },
          },
        ]
      : [
          {
            type: 'value',
            gridIndex: 0,
            scale: true,
            axisLine: { show: false },
            splitLine: { lineStyle: { color: theme.border } },
            axisLabel: { color: theme.secondary },
          },
        ],
    dataZoom: [
      { type: 'inside', xAxisIndex, start, end: 100 },
      {
        type: 'slider',
        xAxisIndex,
        start,
        end: 100,
        bottom: 8,
        height: 18,
        borderColor: theme.border,
        textStyle: { color: theme.secondary },
      },
    ],
    series,
  }
}

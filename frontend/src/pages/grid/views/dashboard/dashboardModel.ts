/** dashboard 配置模型：解析 / 归一 / 白名单裁剪（ADR 0023 P0）.
 *
 * 与后端 `src/cndb/plugins/tables/services/core/dashboard_config.py`
 * 由 `tests/fixtures/dashboard/schema_cases.json` 的同一组用例驱动，防止 TS/Python 口径漂移。
 *
 * 读取时补默认值并裁剪未知键；结构非法抛 `DashboardConfigError`（带 `widgets[i].xxx` 路径），
 * 由 DashboardView 转成可读的空态，避免脏配置炸整页。
 */

import type { Field } from '@/api'
import { FIELD_TYPE_ALIASES } from '../../cells/fieldOps'
import type { WidgetBox } from './dashboardLayout'
import { DASHBOARD_COLS, DASHBOARD_MAX_H, DASHBOARD_MAX_Y } from './dashboardLayout'

export const MAX_DASHBOARD_WIDGETS = 32
export const DASHBOARD_SCHEMA_VERSION = 1

export type DashboardWidgetType = 'chart' | 'kpi' | 'table' | 'text'
export type DashboardChartType =
  | 'bar' | 'line' | 'pie' | 'scatter' | 'histogram' | 'boxplot'
  | 'area' | 'stack' | 'combo' | 'radar' | 'funnel' | 'gauge' | 'heatmap' | 'treemap'
export type DashboardAggregation = 'sum' | 'avg' | 'count' | 'min' | 'max' | 'median'
/** 类目排序口径；asc/desc 为 P0 兼容值，语义等同 y_asc/y_desc */
export type DashboardChartSort = 'none' | 'asc' | 'desc' | 'x_asc' | 'x_desc' | 'y_asc' | 'y_desc'
export type DashboardFilterLogic = 'AND' | 'OR'
export type DashboardGlobalFilterKind = 'date_range' | 'select' | 'search'

export interface DashboardCanvas {
  cols: number
  row_height: number
  gap: number
  padding: number
}

export interface DashboardFilter {
  field_name: string
  op: string
  value?: unknown
}

export interface DashboardSorting {
  field_name: string
  direction: 'asc' | 'desc'
}

export interface DashboardQuery {
  filters: DashboardFilter[]
  filter_logic: DashboardFilterLogic
  sortings: DashboardSorting[]
  limit?: number
}

export interface DashboardChart {
  type: DashboardChartType
  x?: string
  y: string[]
  series?: string
  agg: DashboardAggregation
  stack: 'none' | 'stack' | 'percent'
  sort: DashboardChartSort
  top_n?: number
  dual_axis: boolean
  /** 仪表盘目标值（仅 gauge 使用） */
  target?: number
  format: { unit?: string; decimals?: number }
}

export interface DashboardKpiValue {
  field: string
  agg: DashboardAggregation
}

export interface DashboardKpi {
  value: DashboardKpiValue
  compare?: {
    mode: 'prev_period' | 'prev_year'
    date_field: string
    granularity: 'day' | 'week' | 'month' | 'quarter' | 'year'
  }
  sparkline?: DashboardKpiValue & { points: number }
}

export interface DashboardGlobalFilter {
  id: string
  kind: DashboardGlobalFilterKind
  field: string
  label?: string
}

export interface DashboardThreshold {
  value: number
  color: string
}

export interface DashboardDisplay {
  show_legend?: boolean
  palette?: string
  /** 阈值配色（≤5 项，按 value 升序后「达到阈值」取色） */
  thresholds?: DashboardThreshold[]
}

export interface DashboardWidgetBase {
  id: string
  type: DashboardWidgetType
  title?: string
  layout: WidgetBox
  query: DashboardQuery
  display?: DashboardDisplay
}

export interface DashboardChartWidget extends DashboardWidgetBase {
  type: 'chart'
  chart: DashboardChart
}

export interface DashboardKpiWidget extends DashboardWidgetBase {
  type: 'kpi'
  kpi: DashboardKpi
}

export interface DashboardTextWidget extends DashboardWidgetBase {
  type: 'text'
  text: { content: string }
}

export interface DashboardTableWidget extends DashboardWidgetBase {
  type: 'table'
  table: { columns: string[]; row_limit: number }
}

export type DashboardWidget =
  | DashboardChartWidget
  | DashboardKpiWidget
  | DashboardTextWidget
  | DashboardTableWidget

/** widget 未填标题时的默认展示名 */
export const DASHBOARD_TYPE_LABELS: Record<DashboardWidgetType, string> = {
  chart: '图表',
  kpi: '指标',
  text: '说明',
  table: '明细',
}

export interface DashboardConfig {
  schema_version: 1
  canvas: DashboardCanvas
  widgets: DashboardWidget[]
  global_filters: DashboardGlobalFilter[]
  settings: { refresh_interval: number; theme: 'inherit' | 'light' | 'dark' }
}

/** 结构非法：`path` 定位到 widgets[i].xxx，供 UI / 测试逐条断言 */
export class DashboardConfigError extends Error {
  readonly path: string
  constructor(path: string, message: string) {
    super(`${path}: ${message}`)
    this.name = 'DashboardConfigError'
    this.path = path
  }
}

const ID_RE = /^[a-zA-Z0-9_-]{1,32}$/
const FILTER_OPS = new Set([
  'eq', '=', 'neq', '!=', 'gt', '>', 'gte', '>=', 'lt', '<', 'lte', '<=',
  'in', 'not_in', 'contains', 'starts_with', 'ends_with',
  'is_empty', 'is_not_empty', 'is_null', 'is_not_null',
  'contains_any', 'contains_all', 'between', 'date_range', 'has_any', 'has_all',
])
const NUMERIC_TYPES = new Set(['number', 'float', 'percentage', 'timestamp'])
const DATE_TYPES = new Set(['date', 'datetime'])
const CHART_TYPES = new Set<string>([
  'bar', 'line', 'pie', 'scatter', 'histogram', 'boxplot',
  'area', 'stack', 'combo', 'radar', 'funnel', 'gauge', 'heatmap', 'treemap',
])
const AGGREGATIONS = new Set(['sum', 'avg', 'count', 'min', 'max', 'median'])
const SORT_VALUES = new Set(['none', 'asc', 'desc', 'x_asc', 'x_desc', 'y_asc', 'y_desc'])
const MAX_THRESHOLDS = 5

type Raw = Record<string, unknown>
type FieldTypes = Map<string, string>

const isObj = (v: unknown): v is Raw => typeof v === 'object' && v !== null && !Array.isArray(v)
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)

function fieldType(types: FieldTypes, name: string): string | undefined {
  const raw = types.get(name)
  return raw ? (FIELD_TYPE_ALIASES[raw] ?? raw) : undefined
}

const isNumberType = (types: FieldTypes, name: string): boolean => {
  const t = fieldType(types, name)
  return !!t && NUMERIC_TYPES.has(t)
}
const isDateType = (types: FieldTypes, name: string): boolean => {
  const t = fieldType(types, name)
  return !!t && DATE_TYPES.has(t)
}

/** 校验字段引用；fields 未提供时只校验非空字符串（读取旧配置的宽容路径） */
function requireField(value: unknown, path: string, types: FieldTypes | null): string {
  if (typeof value !== 'string' || !value) throw new DashboardConfigError(path, '必须是非空字段名')
  if (types && !types.has(value)) throw new DashboardConfigError(path, `字段不存在 (${value})`)
  return value
}

function asInt(value: unknown, path: string, low: number, high: number): number {
  if (!isInt(value) || value < low || value > high) {
    throw new DashboardConfigError(path, `必须是 ${low}..${high} 的整数`)
  }
  return value
}

function normalizeFilters(raw: unknown, path: string, types: FieldTypes | null): DashboardFilter[] {
  if (raw == null) return []
  if (!Array.isArray(raw)) throw new DashboardConfigError(path, '必须是数组')
  return raw.map((item, i) => {
    const p = `${path}[${i}]`
    if (!isObj(item)) throw new DashboardConfigError(p, '必须是对象')
    const field_name = requireField(item.field_name, `${p}.field_name`, types)
    const op = item.op
    if (typeof op !== 'string' || !FILTER_OPS.has(op)) {
      throw new DashboardConfigError(`${p}.op`, `不支持的操作符 (${String(op)})`)
    }
    return { field_name, op, value: item.value }
  })
}

function normalizeSortings(raw: unknown, path: string, types: FieldTypes | null): DashboardSorting[] {
  if (raw == null) return []
  if (!Array.isArray(raw)) throw new DashboardConfigError(path, '必须是数组')
  return raw.map((item, i) => {
    const p = `${path}[${i}]`
    if (!isObj(item)) throw new DashboardConfigError(p, '必须是对象')
    const field_name = requireField(item.field_name, `${p}.field_name`, types)
    const direction = item.direction ?? 'asc'
    if (direction !== 'asc' && direction !== 'desc') {
      throw new DashboardConfigError(`${p}.direction`, '必须是 asc/desc')
    }
    return { field_name, direction }
  })
}

function normalizeQuery(raw: unknown, path: string, types: FieldTypes | null): DashboardQuery {
  if (raw == null) return { filters: [], filter_logic: 'AND', sortings: [] }
  if (!isObj(raw)) throw new DashboardConfigError(path, '必须是对象')
  if ('table_id' in raw) throw new DashboardConfigError(`${path}.table_id`, 'P0-P2 禁止跨表')
  const logic = raw.filter_logic ?? 'AND'
  if (logic !== 'AND' && logic !== 'OR') {
    throw new DashboardConfigError(`${path}.filter_logic`, '必须是 AND/OR')
  }
  const query: DashboardQuery = {
    filters: normalizeFilters(raw.filters, `${path}.filters`, types),
    filter_logic: logic,
    sortings: normalizeSortings(raw.sortings, `${path}.sortings`, types),
  }
  if (raw.limit != null) query.limit = asInt(raw.limit, `${path}.limit`, 1, 5000)
  return query
}

function normalizeChart(raw: unknown, path: string, types: FieldTypes | null): DashboardChart {
  if (!isObj(raw)) throw new DashboardConfigError(path, '必须是对象')
  const type = raw.type
  if (typeof type !== 'string' || !CHART_TYPES.has(type)) {
    throw new DashboardConfigError(`${path}.type`, `不支持的图表类型 (${String(type)})`)
  }
  const agg = raw.agg ?? 'sum'
  if (typeof agg !== 'string' || !AGGREGATIONS.has(agg)) {
    throw new DashboardConfigError(`${path}.agg`, `不支持的聚合方式 (${String(agg)})`)
  }
  let x: string | undefined
  // gauge 是单值卡：不需要类目轴（x 可省略）
  if (type !== 'histogram' && type !== 'gauge') x = requireField(raw.x, `${path}.x`, types)
  const yRaw = raw.y
  if (!Array.isArray(yRaw) || yRaw.length === 0) throw new DashboardConfigError(`${path}.y`, '必须是非空数组')
  if (yRaw.length > 8) throw new DashboardConfigError(`${path}.y`, '度量最多 8 个')
  const y = yRaw.map((value, i) => {
    const name = requireField(value, `${path}.y[${i}]`, types)
    if (types) {
      if (agg !== 'count' && !isNumberType(types, name)) {
        throw new DashboardConfigError(`${path}.y[${i}]`, `非数值字段不能用于 ${agg}`)
      }
      if ((type === 'scatter' || type === 'histogram') && !isNumberType(types, name)) {
        throw new DashboardConfigError(`${path}.y[${i}]`, '该图表类型的度量必须是数值字段')
      }
    }
    return name
  })
  if (type === 'scatter' && x && types && !isNumberType(types, x)) {
    throw new DashboardConfigError(`${path}.x`, '散点图 X 轴必须是数值字段')
  }
  let series: string | undefined
  if (raw.series != null) series = requireField(raw.series, `${path}.series`, types)
  // 二维分布 / 层级占比必须给出第二维（series）
  if ((type === 'heatmap' || type === 'treemap') && !series) {
    throw new DashboardConfigError(`${path}.series`, `${type} 必须指定第二维字段`)
  }
  const stack = raw.stack ?? 'none'
  if (stack !== 'none' && stack !== 'stack' && stack !== 'percent') {
    throw new DashboardConfigError(`${path}.stack`, '必须是 none/stack/percent')
  }
  const sort = raw.sort ?? 'none'
  if (typeof sort !== 'string' || !SORT_VALUES.has(sort)) {
    throw new DashboardConfigError(`${path}.sort`, '必须是 none/asc/desc/x_asc/x_desc/y_asc/y_desc')
  }
  const top_n = raw.top_n == null ? undefined : asInt(raw.top_n, `${path}.top_n`, 1, 100)
  const dual_axis = raw.dual_axis ?? false
  if (typeof dual_axis !== 'boolean') throw new DashboardConfigError(`${path}.dual_axis`, '必须是布尔值')
  let target: number | undefined
  if (raw.target != null) {
    if (typeof raw.target !== 'number' || !Number.isFinite(raw.target)) {
      throw new DashboardConfigError(`${path}.target`, '必须是数值')
    }
    target = raw.target
  }
  const fmtRaw = raw.format
  const format: { unit?: string; decimals?: number } = {}
  if (fmtRaw != null) {
    if (!isObj(fmtRaw)) throw new DashboardConfigError(`${path}.format`, '必须是对象')
    if (fmtRaw.unit != null) {
      if (typeof fmtRaw.unit !== 'string' || fmtRaw.unit.length > 16) {
        throw new DashboardConfigError(`${path}.format.unit`, '必须是长度 ≤16 的字符串')
      }
      format.unit = fmtRaw.unit
    }
    if (fmtRaw.decimals != null) format.decimals = asInt(fmtRaw.decimals, `${path}.format.decimals`, 0, 6)
  }
  return {
    type: type as DashboardChartType,
    x,
    y,
    series,
    agg: agg as DashboardAggregation,
    stack,
    sort: sort as DashboardChartSort,
    top_n,
    dual_axis,
    target,
    format,
  }
}

function normalizeAggField(raw: unknown, path: string, types: FieldTypes | null): DashboardKpiValue {
  if (!isObj(raw)) throw new DashboardConfigError(path, '必须是对象')
  const agg = raw.agg ?? 'count'
  if (typeof agg !== 'string' || !AGGREGATIONS.has(agg)) {
    throw new DashboardConfigError(`${path}.agg`, `不支持的聚合方式 (${String(agg)})`)
  }
  const field = requireField(raw.field, `${path}.field`, types)
  if (types && agg !== 'count' && !isNumberType(types, field)) {
    throw new DashboardConfigError(`${path}.field`, `非数值字段不能用于 ${agg}`)
  }
  return { field, agg: agg as DashboardAggregation }
}

function normalizeKpi(raw: unknown, path: string, types: FieldTypes | null): DashboardKpi {
  if (!isObj(raw)) throw new DashboardConfigError(path, '必须是对象')
  const kpi: DashboardKpi = { value: normalizeAggField(raw.value, `${path}.value`, types) }
  if (raw.compare != null) {
    if (!isObj(raw.compare)) throw new DashboardConfigError(`${path}.compare`, '必须是对象')
    const mode = raw.compare.mode
    if (mode !== 'prev_period' && mode !== 'prev_year') {
      throw new DashboardConfigError(`${path}.compare.mode`, '必须是 prev_period/prev_year')
    }
    const date_field = requireField(raw.compare.date_field, `${path}.compare.date_field`, types)
    if (types && !isDateType(types, date_field)) {
      throw new DashboardConfigError(`${path}.compare.date_field`, '必须是日期/时间字段')
    }
    const granularity = raw.compare.granularity ?? 'month'
    if (!['day', 'week', 'month', 'quarter', 'year'].includes(String(granularity))) {
      throw new DashboardConfigError(`${path}.compare.granularity`, '必须是 day/week/month/quarter/year')
    }
    kpi.compare = {
      mode,
      date_field,
      granularity: granularity as NonNullable<DashboardKpi['compare']>['granularity'],
    }
  }
  if (raw.sparkline != null) {
    if (!isObj(raw.sparkline)) throw new DashboardConfigError(`${path}.sparkline`, '必须是对象')
    const value = normalizeAggField(
      { field: raw.sparkline.field, agg: raw.sparkline.agg ?? 'count' },
      `${path}.sparkline`,
      types,
    )
    const points = asInt(raw.sparkline.points ?? 12, `${path}.sparkline.points`, 1, 24)
    kpi.sparkline = { ...value, points }
  }
  return kpi
}

function normalizeTable(raw: unknown, path: string, types: FieldTypes | null): { columns: string[]; row_limit: number } {
  if (!isObj(raw)) throw new DashboardConfigError(path, '必须是对象')
  const colsRaw = raw.columns ?? []
  if (!Array.isArray(colsRaw)) throw new DashboardConfigError(`${path}.columns`, '必须是数组')
  if (colsRaw.length > 8) throw new DashboardConfigError(`${path}.columns`, '最多 8 列')
  const columns = colsRaw.map((c, i) => requireField(c, `${path}.columns[${i}]`, types))
  const row_limit = asInt(raw.row_limit ?? 50, `${path}.row_limit`, 1, 50)
  return { columns, row_limit }
}

function normalizeWidget(raw: unknown, index: number, types: FieldTypes | null, seen: Set<string>): DashboardWidget {
  const path = `widgets[${index}]`
  if (!isObj(raw)) throw new DashboardConfigError(path, '必须是对象')
  const id = raw.id
  if (typeof id !== 'string' || !ID_RE.test(id)) {
    throw new DashboardConfigError(`${path}.id`, '必须是 1..32 位字母数字/下划线/短横线')
  }
  if (seen.has(id)) throw new DashboardConfigError(`${path}.id`, `重复 (${id})`)
  seen.add(id)
  const type = raw.type
  if (type !== 'chart' && type !== 'kpi' && type !== 'table' && type !== 'text') {
    throw new DashboardConfigError(`${path}.type`, '必须是 chart/kpi/table/text')
  }
  if (!isObj(raw.layout)) throw new DashboardConfigError(`${path}.layout`, '必须是对象')
  const layout: WidgetBox = {
    id,
    x: asInt(raw.layout.x, `${path}.layout.x`, 0, DASHBOARD_COLS - 1),
    y: asInt(raw.layout.y, `${path}.layout.y`, 0, DASHBOARD_MAX_Y),
    w: asInt(raw.layout.w, `${path}.layout.w`, 1, DASHBOARD_COLS),
    h: asInt(raw.layout.h, `${path}.layout.h`, 1, DASHBOARD_MAX_H),
  }
  if (layout.x > DASHBOARD_COLS - layout.w) {
    throw new DashboardConfigError(`${path}.layout.x`, `必须是 0..${DASHBOARD_COLS - layout.w}`)
  }
  const title = raw.title == null ? undefined : raw.title
  if (title != null && (typeof title !== 'string' || title.length > 200)) {
    throw new DashboardConfigError(`${path}.title`, '必须是长度 ≤200 的字符串')
  }
  const query = normalizeQuery(raw.query, `${path}.query`, types)
  const base: DashboardWidgetBase = { id, type, title: title as string | undefined, layout, query }
  if (raw.display != null) {
    if (!isObj(raw.display)) throw new DashboardConfigError(`${path}.display`, '必须是对象')
    const display: DashboardDisplay = {}
    if (raw.display.show_legend != null) {
      if (typeof raw.display.show_legend !== 'boolean') {
        throw new DashboardConfigError(`${path}.display.show_legend`, '必须是布尔值')
      }
      display.show_legend = raw.display.show_legend
    }
    if (raw.display.palette != null) {
      if (typeof raw.display.palette !== 'string' || raw.display.palette.length > 32) {
        throw new DashboardConfigError(`${path}.display.palette`, '必须是长度 ≤32 的字符串')
      }
      display.palette = raw.display.palette
    }
    if (raw.display.thresholds != null) {
      if (!Array.isArray(raw.display.thresholds)) {
        throw new DashboardConfigError(`${path}.display.thresholds`, '必须是数组')
      }
      if (raw.display.thresholds.length > MAX_THRESHOLDS) {
        throw new DashboardConfigError(`${path}.display.thresholds`, `最多 ${MAX_THRESHOLDS} 项`)
      }
      display.thresholds = raw.display.thresholds.map((item, i) => {
        const p = `${path}.display.thresholds[${i}]`
        if (!isObj(item)) throw new DashboardConfigError(p, '必须是对象')
        if (typeof item.value !== 'number' || !Number.isFinite(item.value)) {
          throw new DashboardConfigError(`${p}.value`, '必须是数值')
        }
        if (typeof item.color !== 'string' || !item.color || item.color.length > 32) {
          throw new DashboardConfigError(`${p}.color`, '必须是长度 1..32 的字符串')
        }
        return { value: item.value, color: item.color }
      })
    }
    base.display = display
  }
  switch (type) {
    case 'chart':
      return { ...base, type, chart: normalizeChart(raw.chart, `${path}.chart`, types) }
    case 'kpi':
      return { ...base, type, kpi: normalizeKpi(raw.kpi, `${path}.kpi`, types) }
    case 'table':
      return { ...base, type, table: normalizeTable(raw.table, `${path}.table`, types) }
    default: {
      if (!isObj(raw.text) || typeof raw.text.content !== 'string'
        || !raw.text.content.trim() || raw.text.content.length > 20000) {
        throw new DashboardConfigError(`${path}.text.content`, '必须是长度 1..20000 的字符串')
      }
      return { ...base, type: 'text', text: { content: raw.text.content } }
    }
  }
}

function normalizeGlobalFilters(raw: unknown, types: FieldTypes | null): DashboardGlobalFilter[] {
  if (raw == null) return []
  if (!Array.isArray(raw)) throw new DashboardConfigError('global_filters', '必须是数组')
  if (raw.length > 12) throw new DashboardConfigError('global_filters', '最多 12 项')
  const seen = new Set<string>()
  return raw.map((item, i) => {
    const path = `global_filters[${i}]`
    if (!isObj(item)) throw new DashboardConfigError(path, '必须是对象')
    const id = item.id
    if (typeof id !== 'string' || !ID_RE.test(id)) {
      throw new DashboardConfigError(`${path}.id`, '必须是 1..32 位字母数字/下划线/短横线')
    }
    if (seen.has(id)) throw new DashboardConfigError(`${path}.id`, `重复 (${id})`)
    seen.add(id)
    const kind = item.kind
    if (kind !== 'date_range' && kind !== 'select' && kind !== 'search') {
      throw new DashboardConfigError(`${path}.kind`, '必须是 date_range/select/search')
    }
    const field = requireField(item.field, `${path}.field`, types)
    if (types && kind === 'date_range' && !isDateType(types, field)) {
      throw new DashboardConfigError(`${path}.field`, 'date_range 必须引用日期/时间字段')
    }
    const label = item.label
    if (label != null && (typeof label !== 'string' || label.length > 80)) {
      throw new DashboardConfigError(`${path}.label`, '必须是长度 ≤80 的字符串')
    }
    return { id, kind, field, label: label as string | undefined }
  })
}

function normalizeCanvas(raw: Raw): DashboardCanvas {
  const rawCanvas = raw.canvas
  if (rawCanvas != null && !isObj(rawCanvas)) throw new DashboardConfigError('canvas', '必须是对象')
  const canvas = (isObj(rawCanvas) ? rawCanvas : {}) as Raw
  const cols = canvas.cols ?? DASHBOARD_COLS
  if (!isInt(cols) || cols !== DASHBOARD_COLS) {
    throw new DashboardConfigError('canvas.cols', 'P0 固定 12 列')
  }
  const read = (key: string, fallback: number, low: number, high: number): number => {
    const value = canvas[key] ?? raw[key] ?? fallback
    return asInt(value, `canvas.${key}`, low, high)
  }
  return {
    cols,
    row_height: read('row_height', 40, 20, 80),
    gap: read('gap', 12, 0, 32),
    padding: read('padding', 16, 0, 48),
  }
}

/** 解析并归一 dashboard 配置；`fields` 传入时同时校验字段存在与角色类型 */
export function normalizeDashboard(raw: unknown, fields?: Field[]): DashboardConfig {
  if (raw == null) raw = {}
  if (!isObj(raw)) throw new DashboardConfigError('root', 'dashboard 配置必须是对象')
  const types: FieldTypes | null = fields ? new Map(fields.map((f) => [f.name, f.field_type])) : null
  const version = raw.schema_version ?? DASHBOARD_SCHEMA_VERSION
  if (version !== DASHBOARD_SCHEMA_VERSION) throw new DashboardConfigError('schema_version', 'P0 仅支持 1')
  const canvas = normalizeCanvas(raw)
  const rawWidgets = raw.widgets ?? []
  if (!Array.isArray(rawWidgets)) throw new DashboardConfigError('widgets', '必须是数组')
  if (rawWidgets.length > MAX_DASHBOARD_WIDGETS) {
    throw new DashboardConfigError('widgets', `最多 ${MAX_DASHBOARD_WIDGETS} 个`)
  }
  const seen = new Set<string>()
  const widgets = rawWidgets.map((item, i) => normalizeWidget(item, i, types, seen))
  const global_filters = normalizeGlobalFilters(raw.global_filters, types)
  const settingsRaw = raw.settings
  if (settingsRaw != null && !isObj(settingsRaw)) throw new DashboardConfigError('settings', '必须是对象')
  const settingsObj = (isObj(settingsRaw) ? settingsRaw : {}) as Raw
  const refresh_interval = asInt(settingsObj.refresh_interval ?? 0, 'settings.refresh_interval', 0, 3600)
  const theme = settingsObj.theme ?? 'inherit'
  if (theme !== 'inherit' && theme !== 'light' && theme !== 'dark') {
    throw new DashboardConfigError('settings.theme', '必须是 inherit/light/dark')
  }
  return {
    schema_version: 1,
    canvas,
    widgets,
    global_filters,
    settings: { refresh_interval, theme },
  }
}

/** 序列化出口：归一后的对象即白名单结构，直接返回可 JSON 化的副本 */
export function serializeDashboard(config: DashboardConfig): Record<string, unknown> {
  return JSON.parse(JSON.stringify(config)) as Record<string, unknown>
}

/** 空画布默认配置（新建 dashboard 时使用） */
export function defaultDashboardConfig(): DashboardConfig {
  return normalizeDashboard({})
}

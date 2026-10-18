/** 数据分析页纯逻辑层 —— 配置归一化 / 图表映射 / CSV 导出 / 公式编辑辅助.
 *
 * 说明：页面组件只做数据编排与渲染，所有可单测的转换集中在这里（与 grid 视图
 * 的 chartBoard 同思路），避免把统计口径与转义规则埋进 JSX。
 */

import type {
  AnalyticsAgg,
  AnalyticsChart,
  AnalyticsFormula,
  AnalyticsRecommendationExample,
  AnalyticsRecommendationRole,
  AnalyticsSummary,
  AnalyticsSummaryMetric,
  AnalyticsTemplate,
  AnalyticsTemplateConfig,
} from '@/api/analytics'
import type { ChartConfig } from '@/pages/grid/views/chartBoard'

export const AGG_OPTIONS: Array<{ value: AnalyticsAgg; label: string }> = [
  { value: 'sum', label: '求和' },
  { value: 'avg', label: '平均' },
  { value: 'count', label: '计数' },
  { value: 'min', label: '最小' },
  { value: 'max', label: '最大' },
]

export const AGG_LABELS: Record<string, string> = Object.fromEntries(
  AGG_OPTIONS.map(o => [o.value, o.label]),
)

export const AGG_VALUES: AnalyticsAgg[] = AGG_OPTIONS.map(o => o.value)

export const CHART_TYPES: Array<{ value: string; label: string }> = [
  { value: 'bar', label: '柱状图' },
  { value: 'line', label: '折线图' },
  { value: 'pie', label: '饼图' },
  { value: 'scatter', label: '散点图' },
  { value: 'histogram', label: '直方图' },
  { value: 'boxplot', label: '箱线图' },
]

/** 聚合方式对图表类型是否生效（scatter 双数值轴 / histogram 分箱 / boxplot 五数概括不用维度聚合） */
const AGG_CHART_TYPES = new Set(['bar', 'line', 'pie'])

export const DEFAULT_CHART: AnalyticsChart = {
  type: 'bar',
  x: null,
  y: null,
  series: null,
  title: '',
  aggregation: 'sum',
}

export const EMPTY_SUMMARY: AnalyticsSummary = {
  group_by: null,
  metrics: [],
  sort_by: null,
  sort_order: 'desc',
  top_n: null,
}

/** 智能推荐字段角色 → 中文标签（未知角色原样返回） */
const RECOMMENDATION_ROLE_LABELS: Record<AnalyticsRecommendationRole, string> = {
  metric: '指标',
  dimension: '维度',
  time: '时间',
  identifier: '标识',
  ignored: '忽略',
}

export function formatRecommendationRole(role: string): string {
  return RECOMMENDATION_ROLE_LABELS[role as AnalyticsRecommendationRole] ?? role
}

/** 智能推荐字段角色 → antd Tag 颜色 */
export function recommendationRoleColor(role: string): string {
  switch (role) {
    case 'metric':
      return 'green'
    case 'dimension':
      return 'blue'
    case 'time':
      return 'purple'
    case 'identifier':
      return 'orange'
    case 'ignored':
      return 'default'
    default:
      return 'default'
  }
}

/** 智能推荐字段分组顺序（仅这三类参与图表/汇总联动） */
export const RECOMMENDATION_CHIP_ROLES: AnalyticsRecommendationRole[] = [
  'dimension',
  'time',
  'metric',
]

/** 公式键 → 汇总指标键（与后端 compute.metric_key 同一口径） */
export function metricKey(agg: string, field: string): string {
  return `${agg}(${field})`
}

/** 指标展示名（与后端 compute.metric_label 同一口径） */
export function metricLabel(agg: string, field: string, label = ''): string {
  return label || `${AGG_LABELS[agg] ?? agg}(${field})`
}

/** 汇总排序可选项（指标 key → 展示名） */
export function summarySortOptions(summary: AnalyticsSummary): Array<{ value: string; label: string }> {
  return summary.metrics
    .filter(m => m.field)
    .map(m => ({ value: metricKey(m.agg, m.field), label: metricLabel(m.agg, m.field, m.label) }))
}

/** 新建一条空公式行 */
export function newFormula(index: number): AnalyticsFormula {
  return { key: `metric_${index + 1}`, label: '', expr: '' }
}

/** 模板里的公式配置 → 页面编辑态（过滤无效项并补默认键名） */
export function normalizeFormulas(input: AnalyticsFormula[] | undefined | null): AnalyticsFormula[] {
  const list = (input ?? [])
    .filter(f => f && typeof f.key === 'string' && typeof f.expr === 'string')
    .map(f => ({ key: f.key, label: f.label ?? '', expr: f.expr }))
  return list.length ? list : [newFormula(0)]
}

/** 模板里的图表配置 → 页面编辑态（兼容旧模板缺少 aggregation 的情况） */
export function normalizeChart(input: AnalyticsChart | null | undefined): AnalyticsChart {
  if (!input) return { ...DEFAULT_CHART }
  return {
    type: input.type || 'bar',
    x: input.x ?? null,
    y: input.y ?? null,
    series: input.series ?? null,
    title: input.title ?? '',
    aggregation: AGG_VALUES.includes(input.aggregation as AnalyticsAgg)
      ? (input.aggregation as AnalyticsAgg)
      : 'sum',
  }
}

function normalizeMetric(input: AnalyticsSummaryMetric): AnalyticsSummaryMetric | null {
  if (!input || typeof input.field !== 'string' || !input.field) return null
  return {
    field: input.field,
    agg: AGG_VALUES.includes(input.agg) ? input.agg : 'sum',
    label: input.label ?? '',
  }
}

/** 模板里的分组汇总配置 → 页面编辑态 */
export function normalizeSummary(input: AnalyticsSummary | null | undefined): AnalyticsSummary {
  if (!input) return { ...EMPTY_SUMMARY, metrics: [] }
  const metrics = (input.metrics ?? []).map(normalizeMetric).filter((m): m is AnalyticsSummaryMetric => !!m)
  const sortBy = input.sort_by && metrics.some(m => metricKey(m.agg, m.field) === input.sort_by || m.field === input.sort_by)
    ? input.sort_by
    : null
  return {
    group_by: input.group_by ?? null,
    metrics,
    sort_by: sortBy,
    sort_order: input.sort_order === 'asc' ? 'asc' : 'desc',
    top_n: typeof input.top_n === 'number' && input.top_n > 0 ? input.top_n : null,
  }
}

/** 当前编辑态 → 模板配置（过滤空公式；summary 无指标时不落库） */
export function buildTemplateConfig(input: {
  formulas: AnalyticsFormula[]
  chart: AnalyticsChart
  summary: AnalyticsSummary
}): AnalyticsTemplateConfig {
  const formulas = input.formulas
    .filter(f => f.key.trim() && f.expr.trim())
    .map(f => ({ key: f.key.trim(), label: (f.label ?? '').trim(), expr: f.expr.trim() }))
  return {
    formulas,
    chart: { ...input.chart, aggregation: input.chart.aggregation ?? 'sum' },
    summary: input.summary.metrics.length ? input.summary : null,
    fields: [],
    limit: 1000,
  }
}

/**
 * 追加推荐公式：
 * - 忽略空键名 / 空表达式与重复 key（与当前公式、推荐列表内部都去重）；
 * - 当前只有一条空公式时用推荐内容替换（避免留下一条空行）；
 * - 无任何可追加内容时原样返回入参（引用相等，便于调用方判断是否变化）。
 */
export function mergeFormulas(
  current: AnalyticsFormula[],
  recommended: AnalyticsFormula[],
): AnalyticsFormula[] {
  const replaceBlank = current.length === 1 && !current[0]?.expr.trim()
  const base = replaceBlank ? [] : current
  const seen = new Set(base.map(f => f.key.trim()).filter(Boolean))
  const additions: AnalyticsFormula[] = []
  for (const formula of recommended) {
    const key = (formula?.key ?? '').trim()
    const expr = (formula?.expr ?? '').trim()
    if (!key || !expr || seen.has(key)) continue
    seen.add(key)
    additions.push({ key, label: (formula.label ?? '').trim(), expr })
  }
  if (additions.length === 0) return current
  return [...base, ...additions]
}

/** 典型示例配置归一化：formulas / chart / summary 统一走 normalize*，避免脏数据进编辑态 */
export function applyExampleConfig(example: Pick<
  AnalyticsRecommendationExample,
  'formulas' | 'chart' | 'summary'
>): { formulas: AnalyticsFormula[]; chart: AnalyticsChart; summary: AnalyticsSummary } {
  return {
    formulas: normalizeFormulas(example.formulas),
    chart: normalizeChart(example.chart),
    summary: normalizeSummary(example.summary),
  }
}

/** 图表配置 → ChartCard 的 ChartConfig（按图表类型分派字段语义） */
export function toChartConfig(chart: AnalyticsChart): ChartConfig {
  const x = chart.x ?? undefined
  const y = chart.y ?? undefined
  const cfg: ChartConfig = {
    chart_type: chart.type as ChartConfig['chart_type'],
    aggregation: chart.aggregation ?? 'sum',
    show_stats_panel: true,
  }
  if (chart.type === 'scatter') {
    cfg.x_field = x
    cfg.y_field = y
  } else if (chart.type === 'histogram') {
    // 直方图对单个数值列分箱：x 即被分箱的列
    cfg.measure_field = x ?? y
  } else {
    cfg.dimension_field = x
    cfg.measure_field = y
    cfg.group_field = chart.series ?? undefined
  }
  return cfg
}

/** 当前图表类型是否使用聚合方式配置 */
export function chartUsesAggregation(type: string): boolean {
  return AGG_CHART_TYPES.has(type)
}

/** 模板列表下拉选项 */
export function templateOptions(
  templates: AnalyticsTemplate[],
): Array<{ value: number; label: string }> {
  return templates.map(t => ({ value: t.id, label: t.name }))
}

/** 模板数据源表展示名（未指定 / 表已删除时给出可读文案） */
export function templateTableName(
  tables: Array<{ id: number | string; name: string }>,
  tableId: number | string | null | undefined,
): string {
  if (tableId == null) return '未指定数据表'
  const table = tables.find(t => Number(t.id) === Number(tableId))
  return table?.name || `表 #${tableId}`
}

/** 编辑态快照：用于「未保存修改」判定（字段顺序稳定） */
export function templateSnapshot(input: {
  name: string
  description: string
  tableId: number | null
  formulas: AnalyticsFormula[]
  chart: AnalyticsChart
  summary: AnalyticsSummary
}): string {
  return JSON.stringify({
    name: input.name.trim(),
    description: input.description.trim(),
    tableId: input.tableId,
    formulas: input.formulas.map(f => ({ key: f.key, label: f.label ?? '', expr: f.expr })),
    chart: input.chart,
    summary: input.summary,
  })
}

export function isDirty(snapshot: string, current: string): boolean {
  return snapshot !== current
}

/**
 * 公式本地结构校验（与后端语法校验互补）：
 * - 空键名 / 空表达式、键名重复直接标错，避免等 350ms 防抖接口；
 * - 后端返回的语法 / 字段引用错误原样合并。
 */
export function collectFormulaErrors(
  formulas: AnalyticsFormula[],
  serverErrors: Record<string, string> = {},
): Record<string, string> {
  const errors: Record<string, string> = {}
  const seen = new Set<string>()
  for (const formula of formulas) {
    const key = formula.key.trim()
    const hasExpr = !!formula.expr.trim()
    if (!key) {
      if (hasExpr) errors[formula.key] = '键名不能为空'
      continue
    }
    if (seen.has(key)) {
      errors[key] = '键名重复'
      continue
    }
    seen.add(key)
    if (!hasExpr) continue
    if (serverErrors[key]) errors[key] = serverErrors[key]
  }
  // 只保留当前仍在编辑的键，避免删除公式后残留错误提示
  for (const [key, message] of Object.entries(serverErrors)) {
    if (seen.has(key) && !errors[key]) errors[key] = message
  }
  return errors
}

/** 在光标处插入片段（超出范围时追加到末尾），返回新值与光标位置 */
export function insertAtCursor(
  value: string,
  snippet: string,
  position?: number | null,
): { value: string; caret: number } {
  const pos = typeof position === 'number' && position >= 0 && position <= value.length
    ? position
    : value.length
  const next = `${value.slice(0, pos)}${snippet}${value.slice(pos)}`
  return { value: next, caret: pos + snippet.length }
}

/** 表格单元格取值 → CSV 文本（空值空串，含分隔符/引号/换行时按 RFC 4180 转义） */
function csvCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** 二维数据 → 带 BOM 的 CSV 文本（Excel 直接打开中文不乱码） */
export function toCsv(headers: string[], rows: unknown[][]): string {
  const lines = [headers.map(csvCell).join(','), ...rows.map(row => row.map(csvCell).join(','))]
  return `\uFEFF${lines.join('\r\n')}`
}

/** 数值展示：整数原样，浮点保留 4 位有效数字，空值「—」 */
export function formatNumber(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return Number.isInteger(value) ? String(value) : String(parseFloat(value.toPrecision(4)))
}

/** 非空率（0~1）；分母为 0 时返回 null */
export function nonNullRatio(count: number, missing: number): number | null {
  const total = count + missing
  if (total <= 0) return null
  return count / total
}

/** 文件名安全化（去掉路径分隔符与控制字符） */
export function safeFileName(name: string, fallback = '分析结果'): string {
  const forbidden = new Set(['\\', '/', ':', '*', '?', '"', '<', '>', '|'])
  const cleaned = Array.from(name)
    .filter(ch => ch.charCodeAt(0) > 31 && !forbidden.has(ch))
    .join('')
    .trim()
  return cleaned || fallback
}

/** 触发浏览器下载文本文件（CSV 已带 BOM） */
export function downloadTextFile(filename: string, content: string, mime = 'text/csv;charset=utf-8'): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  triggerDownload(filename, url)
  // 延迟释放，避免部分浏览器下载中断
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 触发浏览器下载 URL（如 ECharts 生成的 dataURL） */
export function triggerDownload(filename: string, url: string): void {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

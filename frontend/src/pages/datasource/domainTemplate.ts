/** 领域模板套用 —— 把模板里的「provider 默认字段名」翻译成目标表的实际字段名.
 *
 * 领域模板（`/datasource/domain-templates`）按 provider 默认输出命名（`close` /
 * `trade_date` / `symbol`…）。同步任务若配了 `field_mapping` 改了名或丢弃了字段，
 * 原样提交会被后端 `normalize_config` 拒绝（400「公式引用了不存在的字段」）。
 * 这里按映射先翻译，翻译不了的部件剔除并回报，避免整份模板套用失败。
 */

import type { AnalyticsChart, AnalyticsFormula, AnalyticsSummary, AnalyticsTemplateConfig } from '@/api/analytics'
import type { DomainTemplate, SyncFieldMapping } from '@/api'

/** 套用结果：可提交的配置 + 被跳过的部件（字段已被映射丢弃） */
export interface MaterializedTemplate {
  config: AnalyticsTemplateConfig
  skipped: string[]
}

interface RenameContext {
  /** 源字段名 → 目标字段名（仅记录真正改名的） */
  rename: Map<string, string>
  /** 被 `null` 显式丢弃的源字段名 */
  dropped: Set<string>
  /** 模板内公式 key：不是字段，不参与翻译 */
  keys: Set<string>
  /** 已被剔除的公式 key（引用它们的图表 / 汇总也要跟着剔除） */
  invalidKeys: Set<string>
}

/** 解析 `field_mapping`：`{源字段: {name} | "目标名" | null}` */
export function buildRenameContext(mapping: SyncFieldMapping | null | undefined, keys: Set<string> = new Set()): RenameContext {
  const rename = new Map<string, string>()
  const dropped = new Set<string>()
  for (const [source, transform] of Object.entries(mapping ?? {})) {
    if (transform === null) {
      dropped.add(source)
      continue
    }
    const target = typeof transform === 'string' ? transform : transform.name
    if (target && target !== source) rename.set(source, target)
  }
  return { rename, dropped, keys, invalidKeys: new Set<string>() }
}

interface Translation {
  /** 翻译后的名字；`dropped` 为 true 时无意义 */
  value: string | null
  dropped: boolean
}

function translateRef(name: string | null | undefined, ctx: RenameContext): Translation | null {
  if (name == null || name === '') return null
  if (ctx.keys.has(name)) {
    return ctx.invalidKeys.has(name) ? { value: null, dropped: true } : { value: name, dropped: false }
  }
  if (ctx.dropped.has(name)) return { value: null, dropped: true }
  return { value: ctx.rename.get(name) ?? name, dropped: false }
}

const FIELD_REF = /\[([^\]]+)\]/g
const METRIC_REF = /^([A-Za-z_]+)\((.+)\)$/

/** 翻译公式表达式里的 `[字段]`；返回被丢弃的字段名 */
function translateExpr(expr: string, ctx: RenameContext): { expr: string; dropped: string[] } {
  const dropped: string[] = []
  const translated = expr.replace(FIELD_REF, (_match, name: string) => {
    const ref = translateRef(name, ctx)
    if (ref?.dropped) dropped.push(name)
    return `[${ref?.value ?? name}]`
  })
  return { expr: translated, dropped }
}

function materializeFormulas(
  raw: unknown[],
  ctx: RenameContext,
  skipped: string[],
): { formulas: AnalyticsFormula[]; droppedKeys: Set<string> } {
  const formulas: AnalyticsFormula[] = []
  const droppedKeys = new Set<string>()
  for (const item of raw as AnalyticsFormula[]) {
    const label = item.label ?? item.key
    const expr = translateExpr(item.expr, ctx)
    const partition = translateRef(item.partition_by, ctx)
    const order = translateRef(item.order_by, ctx)
    const blocked = [...expr.dropped, ...(partition?.dropped ? [item.partition_by as string] : []), ...(order?.dropped ? [item.order_by as string] : [])]
    if (blocked.length > 0) {
      skipped.push(`公式「${label}」`)
      droppedKeys.add(item.key)
      continue
    }
    formulas.push({
      ...item,
      expr: expr.expr,
      partition_by: partition?.value ?? null,
      order_by: order?.value ?? null,
    })
  }
  return { formulas, droppedKeys }
}

function materializeChart(raw: unknown, ctx: RenameContext, skipped: string[]): AnalyticsChart | null {
  if (raw == null) return null
  const chart = raw as AnalyticsChart
  const x = translateRef(chart.x, ctx)
  const y = translateRef(chart.y, ctx)
  const series = translateRef(chart.series, ctx)
  if (x?.dropped || y?.dropped || series?.dropped) {
    skipped.push(`图表「${chart.title || chart.type}」`)
    return null
  }
  return {
    ...chart,
    x: x?.value ?? null,
    y: y?.value ?? null,
    series: series?.value ?? null,
  }
}

function materializeSummary(raw: unknown, ctx: RenameContext, skipped: string[]): AnalyticsSummary | null {
  if (raw == null) return null
  const summary = raw as AnalyticsSummary
  const group = translateRef(summary.group_by, ctx)
  if (group?.dropped) {
    skipped.push(`分组汇总（分组字段 ${summary.group_by}）`)
    return null
  }

  const metrics: AnalyticsSummary['metrics'] = []
  const available = new Set<string>()
  for (const metric of summary.metrics ?? []) {
    const ref = translateRef(metric.field, ctx)
    if (ref?.dropped) {
      skipped.push(`汇总指标「${metric.label || `${metric.agg}(${metric.field})`}」`)
      continue
    }
    metrics.push({ ...metric, field: ref?.value ?? metric.field })
    available.add(`${metric.agg}(${ref?.value ?? metric.field})`)
    available.add(ref?.value ?? metric.field)
  }
  if (metrics.length === 0) {
    skipped.push('分组汇总（指标全部不可用）')
    return null
  }

  // sort_by 形如 `avg(close)` / `count(link)`，也可能直接是字段或公式 key
  const metricMatch = METRIC_REF.exec(summary.sort_by ?? '')
  const sortRef = metricMatch ? translateRef(metricMatch[2], ctx) : translateRef(summary.sort_by, ctx)
  const sortBy = sortRef && !sortRef.dropped
    ? metricMatch
      ? `${metricMatch[1]}(${sortRef.value ?? metricMatch[2]})`
      : sortRef.value
    : null
  return {
    ...summary,
    group_by: group?.value ?? null,
    metrics,
    sort_by: sortBy && available.has(sortBy) ? sortBy : null,
  }
}

/** 把领域模板转换成可直接提交的分析模板配置（字段名按任务映射对齐） */
export function materializeDomainTemplate(
  template: DomainTemplate,
  mapping: SyncFieldMapping | null | undefined,
): MaterializedTemplate {
  const rawFormulas = template.formulas ?? []
  const keys = new Set(rawFormulas.map(item => String((item as { key?: unknown }).key ?? '')).filter(Boolean))
  const ctx = buildRenameContext(mapping, keys)
  const skipped: string[] = []
  const { formulas, droppedKeys } = materializeFormulas(rawFormulas, ctx, skipped)
  ctx.invalidKeys = droppedKeys
  return {
    config: {
      formulas,
      chart: materializeChart(template.chart, ctx, skipped),
      summary: materializeSummary(template.summary, ctx, skipped),
      fields: [],
      limit: 1000,
    },
    skipped,
  }
}

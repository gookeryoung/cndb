/** dashboard 模板：提取 / 字段引用收集 / 落地映射（ADR 0023 P3）.
 *
 * 模板只保存「结构 + 字段名/类型快照」，**不保存来源表**：
 * - 另存时剥离 `query.table_id`，并为被引用的字段记录类型快照（含跨表 widget
 *   引用字段 —— 按目标表 schema 补录，基表字段优先，同名冲突不覆盖）；
 * - 落地时按目标表「同名同类型」认领，认领不到的字段由 UI 提示用户一键改，
 *   其余不做猜测（避免把不兼容字段静默写进配置）；
 * - 最终仍走 `normalizeDashboard` 的唯一校验入口，模板不是后门。
 */

import type { Field } from '@/api'
import { FIELD_TYPE_ALIASES } from '../../cells/fieldOps'
import {
  DashboardConfigError,
  normalizeDashboard,
  serializeDashboard,
  type DashboardConfig,
} from './dashboardModel'

/** 字段引用位置（相对配置根的路径段，用于落地时重写字段名） */
export interface TemplateFieldRef {
  path: Array<string | number>
  field: string
}

/** 模板中未能自动认领的字段（需用户在落地对话框中指定目标字段） */
export interface TemplateFieldIssue {
  field: string
  type: string
}

export interface TemplatePlan {
  /** 自动认领的字段映射：模板字段名 -> 目标字段名 */
  mapping: Record<string, string>
  issues: TemplateFieldIssue[]
}

export interface BuiltDashboardTemplate {
  config: Record<string, unknown>
  fields: Record<string, string>
}

type Raw = Record<string, unknown>

const isObj = (v: unknown): v is Raw => typeof v === 'object' && v !== null && !Array.isArray(v)

function normType(type: string | undefined): string {
  if (!type) return ''
  return FIELD_TYPE_ALIASES[type] ?? type
}

/** 收集配置中所有字段引用（按结构遍历，未知类型 / 损坏项跳过） */
export function collectTemplateRefs(config: Record<string, unknown>): TemplateFieldRef[] {
  const refs: TemplateFieldRef[] = []
  const push = (path: Array<string | number>, value: unknown) => {
    if (typeof value === 'string' && value) refs.push({ path, field: value })
  }
  const widgets = Array.isArray(config.widgets) ? config.widgets : []
  widgets.forEach((widget, i) => {
    if (!isObj(widget)) return
    const base: Array<string | number> = ['widgets', i]
    const query = isObj(widget.query) ? widget.query : {}
    if (Array.isArray(query.filters)) {
      query.filters.forEach((rule, j) => {
        if (isObj(rule)) push([...base, 'query', 'filters', j, 'field_name'], rule.field_name)
      })
    }
    if (Array.isArray(query.sortings)) {
      query.sortings.forEach((rule, j) => {
        if (isObj(rule)) push([...base, 'query', 'sortings', j, 'field_name'], rule.field_name)
      })
    }
    if (widget.type === 'chart' && isObj(widget.chart)) {
      push([...base, 'chart', 'x'], widget.chart.x)
      const y = widget.chart.y
      if (Array.isArray(y)) y.forEach((name, j) => push([...base, 'chart', 'y', j], name))
      push([...base, 'chart', 'series'], widget.chart.series)
    }
    if (widget.type === 'kpi' && isObj(widget.kpi)) {
      const value = isObj(widget.kpi.value) ? widget.kpi.value : {}
      push([...base, 'kpi', 'value', 'field'], value.field)
      const compare = isObj(widget.kpi.compare) ? widget.kpi.compare : {}
      push([...base, 'kpi', 'compare', 'date_field'], compare.date_field)
      const sparkline = isObj(widget.kpi.sparkline) ? widget.kpi.sparkline : {}
      push([...base, 'kpi', 'sparkline', 'field'], sparkline.field)
    }
    if (widget.type === 'table' && isObj(widget.table)) {
      const columns = widget.table.columns
      if (Array.isArray(columns)) columns.forEach((name, j) => push([...base, 'table', 'columns', j], name))
    }
  })
  const globals = Array.isArray(config.global_filters) ? config.global_filters : []
  globals.forEach((item, i) => {
    if (isObj(item)) push(['global_filters', i, 'field'], item.field)
  })
  return refs
}

/** 收集配置中跨表 widget 引用的目标表 id（另存模板时据此补录字段类型快照） */
export function collectTemplateTableIds(config: Record<string, unknown>): string[] {
  const ids = new Set<string>()
  const widgets = Array.isArray(config.widgets) ? config.widgets : []
  for (const widget of widgets) {
    if (!isObj(widget) || !isObj(widget.query)) continue
    const tableId = widget.query.table_id
    if ((typeof tableId === 'number' && tableId > 0) || (typeof tableId === 'string' && tableId)) {
      ids.add(String(tableId))
    }
  }
  return Array.from(ids)
}

/**
 * 另存为模板：剥离来源表，并附上被引用字段的类型快照.
 *
 * `extraFields` 是跨表 widget 目标表的字段（按表 id 索引），由调用方在另存前拉取；
 * 快照按「基表优先、同名字段不覆盖」合并，冲突时以基表类型为准（模板落地仍需人工映射兜底）。
 */
export function buildDashboardTemplate(
  config: DashboardConfig,
  fields: Field[],
  extraFields: Record<string, Field[]> = {},
): BuiltDashboardTemplate {
  const plain = JSON.parse(JSON.stringify(serializeDashboard(config))) as Raw
  const tableIds = collectTemplateTableIds(plain)
  // 模板不硬编码来源表；跨表配置的 table_id 在另存时统一剥离
  if (Array.isArray(plain.widgets)) {
    for (const widget of plain.widgets) {
      if (isObj(widget) && isObj(widget.query)) delete widget.query.table_id
    }
  }
  const referenced = new Set(collectTemplateRefs(plain).map((ref) => ref.field))
  const snapshot: Record<string, string> = {}
  const merge = (list: Field[]) => {
    for (const field of list) {
      if (!referenced.has(field.name) || snapshot[field.name] !== undefined) continue
      snapshot[field.name] = field.field_type
    }
  }
  merge(fields)
  for (const id of tableIds) merge(extraFields[id] ?? [])
  return { config: plain, fields: snapshot }
}

/** 按「同名同类型」自动认领；类型未知（旧模板无快照）时只按名称认领 */
export function planTemplateFields(
  templateFields: Record<string, string>,
  targetFields: Field[],
): TemplatePlan {
  const mapping: Record<string, string> = {}
  const issues: TemplateFieldIssue[] = []
  for (const [name, type] of Object.entries(templateFields)) {
    const wanted = normType(type)
    const hit = targetFields.find(
      (field) => field.name === name && (!wanted || normType(field.field_type) === wanted),
    )
    if (hit) mapping[name] = hit.name
    else issues.push({ field: name, type })
  }
  return { mapping, issues }
}

/** 缺失字段的可选目标字段：优先同类型，同类型为空时退回全部（由用户自行判断） */
export function matchingTargetFields(targetFields: Field[], type: string): Field[] {
  const wanted = normType(type)
  if (!wanted) return targetFields
  const same = targetFields.filter((field) => normType(field.field_type) === wanted)
  return same.length ? same : targetFields
}

function setPath(target: unknown, path: Array<string | number>, value: string): void {
  let node: unknown = target
  for (const key of path.slice(0, -1)) {
    if (typeof node !== 'object' || node === null) return
    node = (node as Record<string | number, unknown>)[key]
  }
  if (typeof node !== 'object' || node === null) return
  const last = path[path.length - 1];
  (node as Record<string | number, unknown>)[last] = value
}

/** 按映射重写字段引用（返回新对象，不修改入参） */
export function applyTemplateMapping(
  config: Record<string, unknown>,
  mapping: Record<string, string>,
): Record<string, unknown> {
  const out = JSON.parse(JSON.stringify(config)) as Raw
  for (const ref of collectTemplateRefs(out)) {
    const next = mapping[ref.field]
    if (next && next !== ref.field) setPath(out, ref.path, next)
  }
  return out
}

/** 落地模板：重写字段引用后走统一校验，返回可直接使用的配置 */
export function applyDashboardTemplate(
  config: Record<string, unknown>,
  mapping: Record<string, string>,
  targetFields: Field[],
): DashboardConfig {
  const rewritten = applyTemplateMapping(config, mapping)
  try {
    return normalizeDashboard(rewritten, targetFields)
  } catch (error) {
    // 模板落地失败时补一句来源提示，便于对话框直接展示
    if (error instanceof DashboardConfigError) {
      throw new DashboardConfigError(error.path, `${error.message.split(': ').slice(1).join(': ')}（模板落地失败）`)
    }
    throw error
  }
}

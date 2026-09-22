/** 看板纯逻辑层 — 卡片排序、紧急级别、分组聚合（与 UI 解耦，可独立单测）.
 *
 * 从 KanbanView.tsx 抽取：
 * - getUrgencyRank / getPriorityRank / compareField / sortKanbanCards：原样迁移
 * - resolveGroupField / groupKanbanColumns：分组聚合逻辑（link/multi_select/select 按首值标签分列）
 */

import type { RowResponse, Field } from '@/api'
import { extractSelectOptions } from './fieldOps'
import { parseDate, daysFromToday } from './dateUtils'
import { getSelectLabel, getLinkFirstLabel, getMultiSelectFirstLabel, formatMultiSelectValue } from './fieldValueFormat'

// ── 类型 ──────────────────────────────────────────────

/** 单个看板列的数据（KanbanColumn 组件的输入） */
export interface KanbanColumnData {
  /** 列 key（React key 用，分组场景与 title 相同；无分组时为 'all'） */
  key: string
  /** 列标题（分组值，空值归 '未分组'） */
  title: string
  /** 列内卡片（已按 sortKanbanCards 排序） */
  rows: RowResponse[]
  /** 列内紧急/逾期卡片数（列头红色徽章） */
  urgentCount: number
  /** 分组字段在该列的原始值 —— 新增卡片时用于预填 group_field；无分组或无法确定时为 undefined */
  rawValue?: unknown
}

// ── 紧急级别与优先级 ──────────────────────────────────

/** 计算卡片紧急级别（0=正常, 1=紧急, 2=逾期），用于置顶排序 */
export function getUrgencyRank(
  row: RowResponse,
  dueDateField?: string,
  urgentThreshold = 3,
): number {
  if (!dueDateField) return 0
  const due = parseDate(row[dueDateField])
  if (!due) return 0
  const dl = daysFromToday(due)
  if (dl < 0) return 2
  if (dl <= urgentThreshold) return 1
  return 0
}

// ── 完成标志判定 ──────────────────────────────────────

/** 完成标志上下文（从 opts 解析一次，行级判定复用） */
export interface DoneCtx {
  /** 完成标志字段名 */
  field: string
  /** 匹配值：boolean | string | string[]（按字段类型） */
  value: unknown
  /** 字段定义（用于类型分派与 select options 提取） */
  fieldDef?: Field
}

/** 从 opts 解析完成标志配置（view_options.done_field + done_value）；未配置或不完整返回 null */
export function resolveDoneCtx(opts: Record<string, unknown>, fields: Field[]): DoneCtx | null {
  const field = opts.done_field as string | undefined
  const value = opts.done_value
  // 注意：value === false 是布尔字段的合法配置值，不能当"未配置"过滤
  if (!field || value === undefined || value === null || value === '') return null
  return { field, value, fieldDef: fields.find((f) => f.name === field) }
}

/** 判定单行是否匹配完成标志（ctx 为 null 时恒 false）.
 *
 * 按字段类型分派：
 * - boolean: 严格相等（false 是合法匹配值）
 * - select: 匹配 option 的 value 或 label（兼容旧 list[str] config，与 getPriorityRank 先例一致）
 * - multiselect: 行值数组与配置值数组任一交集（value/label 归一后比较）
 * - text/longtext/其他: 去首尾空格后精确相等
 */
export function isDoneRow(row: RowResponse, ctx: DoneCtx | null): boolean {
  if (!ctx) return false
  const raw = row[ctx.field]
  const ft = ctx.fieldDef?.field_type

  if (ft === 'boolean') {
    return raw === ctx.value
  }

  if (ft === 'select') {
    if (raw === null || raw === undefined || raw === '') return false
    const strVal = String(raw)
    const options = ctx.fieldDef?.config ? extractSelectOptions(ctx.fieldDef.config) : []
    if (options.length) {
      const hit = options.find((o) => o.value === strVal || o.label === strVal)
      // 行值命中 option 时，比较命中项的 value/label 与配置值；未命中 option 时直接比较原值
      if (hit) return hit.value === ctx.value || hit.label === ctx.value
      return strVal === String(ctx.value)
    }
    return strVal === String(ctx.value)
  }

  if (ft === 'multiselect' || ft === 'multi_select') {
    const rowVals = formatMultiSelectValue(raw)
    if (!rowVals.length) return false
    const cfgVals = Array.isArray(ctx.value) ? ctx.value.map(String) : [String(ctx.value)]
    const options = ctx.fieldDef?.config ? extractSelectOptions(ctx.fieldDef.config) : []
    // 行值与配置值都先归一为 option value（label → value），再求交集
    const toValue = (s: string): string => {
      const hit = options.find((o) => o.value === s || o.label === s)
      return hit ? hit.value : s
    }
    const rowSet = new Set(rowVals.map(toValue))
    return cfgVals.some((v) => rowSet.has(toValue(v)))
  }

  // text / longtext 及其他类型：精确匹配（去首尾空格）
  if (raw === null || raw === undefined) return false
  return String(raw).trim() === String(ctx.value).trim()
}

/** 按优先级字段值计算排序权重（高→低） */
export function getPriorityRank(_row: RowResponse, field?: Field, value?: unknown): number {
  if (!field || !field.config) return 0
  const options = extractSelectOptions(field.config)
  if (!options.length) return 0
  const strVal = String(value ?? '')
  // options 数组靠前的视为更高优先级 —— 索引越小权重越大
  const idx = options.findIndex((o) => o.value === strVal || o.label === strVal)
  return idx >= 0 ? options.length - idx : 0
}

// ── 字段比较器 ────────────────────────────────────────

/** 单字段比较器：按字段类型正确比较两个 row */
export function compareField(
  a: RowResponse,
  b: RowResponse,
  fieldName: string,
  fields: Field[],
  direction: 'asc' | 'desc',
): number {
  const field = fields.find((f) => f.name === fieldName)
  const av = a[fieldName]
  const bv = b[fieldName]
  // null/undefined 排末尾
  const aEmpty = av === null || av === undefined || av === ''
  const bEmpty = bv === null || bv === undefined || bv === ''
  if (aEmpty && bEmpty) return 0
  if (aEmpty) return 1
  if (bEmpty) return -1

  let cmp = 0
  if (field && ['number', 'decimal', 'float', 'percentage', 'timestamp'].includes(field.field_type)) {
    cmp = Number(av) - Number(bv)
  } else if (field && ['date', 'datetime'].includes(field.field_type)) {
    const ad = new Date(String(av)).getTime()
    const bd = new Date(String(bv)).getTime()
    cmp = ad - bd
  } else {
    cmp = String(av).localeCompare(String(bv), 'zh-CN')
  }
  return direction === 'asc' ? cmp : -cmp
}

// ── 卡片排序 ──────────────────────────────────────────

/** 对一列卡片应用完整排序：先紧急置顶，再按 card_sort_field / 级联 view_sortings 排序 */
export function sortKanbanCards(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
  viewSortings: Array<{ field_name: string; direction: 'asc' | 'desc' }> = [],
): RowResponse[] {
  // opts 已由 KanbanView 顶层 resolveOpts 统一默认值，此处直接取值即可
  const urgentThreshold = Number(opts.urgent_threshold_days)
  const dueDateField = opts.due_date_field as string | undefined
  const priorityField = opts.priority_field as string | undefined
  const pinUrgent = opts.pin_urgent !== false && !!dueDateField
  const cardSortField = opts.card_sort_field as string | undefined
  const cardSortDir = opts.card_sort_direction as 'asc' | 'desc'
  const priorityFieldDef = priorityField ? fields.find((f) => f.name === priorityField) : undefined
  // 完成卡片不参与紧急置顶（完成态优先于逾期/紧急）
  const doneCtx = resolveDoneCtx(opts, fields)

  // 把所有排序规则拼成有序列表
  // 优先级：紧急置顶 > card_sort_field > 级联 view_sortings > 优先级权重 > 创建时间倒序
  const sortKeys: Array<{ field_name: string; direction: 'asc' | 'desc' }> = []
  if (cardSortField) sortKeys.push({ field_name: cardSortField, direction: cardSortDir })
  for (const s of viewSortings) {
    if (s.field_name === cardSortField) continue // 去重
    sortKeys.push(s)
  }

  return [...rows].sort((a, b) => {
    // 1) 紧急置顶（逾期 > 紧急 > 正常）；完成卡片视为正常不置顶
    if (pinUrgent) {
      const au = isDoneRow(a, doneCtx) ? 0 : getUrgencyRank(a, dueDateField, urgentThreshold)
      const bu = isDoneRow(b, doneCtx) ? 0 : getUrgencyRank(b, dueDateField, urgentThreshold)
      if (au !== bu) return bu - au // 权重 2 排在最前
    }

    // 2) 应用配置的字段排序
    for (const sk of sortKeys) {
      const c = compareField(a, b, sk.field_name, fields, sk.direction)
      if (c !== 0) return c
    }

    // 3) 按优先级字段权重（如果有配置且未在 sortKeys 中）
    if (priorityField && !sortKeys.some((s) => s.field_name === priorityField)) {
      const pwA = getPriorityRank(a, priorityFieldDef, a[priorityField])
      const pwB = getPriorityRank(b, priorityFieldDef, b[priorityField])
      if (pwA !== pwB) return pwB - pwA
    }

    // 4) 兜底：创建时间倒序（新的在前）或 id 倒序
    const aCreated = (a.created_at as string | undefined) || ''
    const bCreated = (b.created_at as string | undefined) || ''
    if (aCreated && bCreated) {
      const c = bCreated.localeCompare(aCreated)
      if (c !== 0) return c
    }
    return (b.id as number) - (a.id as number)
  })
}

// ── 分组聚合 ──────────────────────────────────────────

/** 解析看板分组字段：优先 view_options.group_field，否则自动取首个 select/multi_select/link 字段 */
export function resolveGroupField(fields: Field[], opts: Record<string, unknown>): { name?: string; def?: Field } {
  const name =
    (opts.group_field as string) ||
    fields.find((f) => f.field_type === 'select' || f.field_type === 'multi_select' || f.field_type === 'link')?.name
  const def = name ? fields.find((f) => f.name === name) : undefined
  return { name, def }
}

/** 计算单行在分组字段上的列 key（link/multi_select/select 按首值标签，空值归 '未分组'） */
function groupKeyForRow(row: RowResponse, groupField: string, groupFieldDef: Field | undefined): string {
  const rawVal = row[groupField]
  let key: string

  if (groupFieldDef) {
    const ft = groupFieldDef.field_type
    if (ft === 'link') {
      key = getLinkFirstLabel(rawVal)
    } else if (ft === 'multi_select' || ft === 'multiselect') {
      key = getMultiSelectFirstLabel(rawVal)
    } else if (ft === 'select') {
      key = getSelectLabel(groupFieldDef, rawVal) || String(rawVal || '')
    } else {
      key = rawVal !== null && rawVal !== undefined && rawVal !== '' ? String(rawVal) : ''
    }
  } else {
    // 未知字段类型，保守兜底
    if (Array.isArray(rawVal)) {
      const first = rawVal[0]
      key = first && typeof first === 'object'
        ? String((first as Record<string, unknown>).value ?? (first as Record<string, unknown>).id ?? '')
        : String(first ?? '')
    } else if (rawVal && typeof rawVal === 'object') {
      const o = rawVal as Record<string, unknown>
      key = String(o.value ?? o.label ?? o.id ?? '')
    } else {
      key = rawVal !== null && rawVal !== undefined && rawVal !== '' ? String(rawVal) : ''
    }
  }

  if (!key) key = '未分组'
  return key
}

/** 从单行的 group_field 值里提取原始值（用于新增卡片预填）—— 与 groupKeyForRow 分支对齐 */
function extractRawGroupValue(row: RowResponse, groupField: string, groupFieldDef: Field | undefined): unknown {
  const rawVal = row[groupField]
  if (rawVal === null || rawVal === undefined || rawVal === '') return undefined
  if (groupFieldDef) {
    const ft = groupFieldDef.field_type
    if (ft === 'multi_select' || ft === 'multiselect') {
      return Array.isArray(rawVal) ? rawVal[0] : rawVal
    }
    if (ft === 'link') {
      // link 字段通常是 id 或 id 数组，取首值
      return Array.isArray(rawVal) ? rawVal[0] : rawVal
    }
    // select 及其它：直接返回原始值
    return rawVal
  }
  return rawVal
}

/** 按分组字段聚合成看板列：每列先排序（sortKanbanCards），再统计紧急/逾期卡片数 */
export function groupKanbanColumns(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
  groupField: string | undefined,
  groupFieldDef: Field | undefined,
  sortings: Array<{ field_name: string; direction: 'asc' | 'desc' }> = [],
): KanbanColumnData[] {
  const cols: KanbanColumnData[] = []

  // 统计每个分组的紧急/逾期卡片数（opts 已 resolve，直接取值）
  const urgentThreshold = Number(opts.urgent_threshold_days)
  const dueDateField = opts.due_date_field as string | undefined
  // 完成卡片不计入紧急数（完成态优先于逾期/紧急）
  const doneCtx = resolveDoneCtx(opts, fields)

  const makeCol = (key: string, title: string, list: RowResponse[], rawValue?: unknown) => {
    const sorted = sortKanbanCards(list, fields, opts, sortings)
    let urgentCount = 0
    if (dueDateField) {
      for (const r of sorted) {
        if (isDoneRow(r, doneCtx)) continue
        const dueDate = parseDate(r[dueDateField])
        if (!dueDate) continue
        const dl = daysFromToday(dueDate)
        if (dl < 0 || dl <= urgentThreshold) urgentCount++
      }
    }
    cols.push({ key, title, rows: sorted, urgentCount, rawValue })
  }

  if (!groupField) {
    // 无分组 → 单列，rawValue 无意义
    makeCol('all', '全部', rows)
    return cols
  }

  const groups = new Map<string, { rows: RowResponse[]; rawValue: unknown }>()
  for (const r of rows) {
    const key = groupKeyForRow(r, groupField, groupFieldDef)
    let bucket = groups.get(key)
    if (!bucket) {
      bucket = { rows: [], rawValue: extractRawGroupValue(r, groupField, groupFieldDef) }
      groups.set(key, bucket)
    }
    bucket.rows.push(r)
  }

  for (const [title, bucket] of groups) {
    makeCol(title, title, bucket.rows, bucket.rawValue)
  }

  return cols
}

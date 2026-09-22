/** 看板纯逻辑层 — 卡片排序、紧急级别、分组聚合（与 UI 解耦，可独立单测）.
 *
 * 从 KanbanView.tsx 抽取：
 * - getUrgencyRank / getPriorityRank / compareField / sortKanbanCards：原样迁移
 * - resolveGroupField / groupKanbanColumns：分组聚合逻辑（link/multi_select/select 按首值标签分列）
 */

import type { RowResponse, Field } from '@/api'
import dayjs from 'dayjs'
import { extractSelectOptions, matchValueCondition } from '../cells/fieldOps'
import { parseDate, daysFromToday } from '../cells/dateUtils'
import { getSelectLabel, getLinkFirstLabel, getMultiSelectFirstLabel, formatMultiSelectValue } from '../cells/fieldValueFormat'

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
  /** 判定操作符 —— 复用筛选契约（FIELD_OPS_BY_TYPE），缺省 '=' 等值；is_empty/is_not_empty 无值直通 */
  op: string
  /** 匹配值：boolean | string | string[]（按字段类型）；无值操作符下为 undefined */
  value: unknown
  /** 字段定义（用于类型分派与 select options 提取） */
  fieldDef?: Field
}

/** 从 opts 解析完成标志配置（view_options.done_field + done_op + done_value）；未配置或不完整返回 null.
 *
 * done_op 缺省 '='（旧数据零迁移）；无值操作符（is_empty/is_not_empty）不要求 done_value。
 */
export function resolveDoneCtx(opts: Record<string, unknown>, fields: Field[]): DoneCtx | null {
  const field = opts.done_field as string | undefined
  if (!field) return null
  const op = typeof opts.done_op === 'string' && opts.done_op ? opts.done_op : '='
  const value = opts.done_value
  // 等值操作符必须有匹配值；注意 value === false 是布尔字段的合法配置值，不能当"未配置"过滤
  if (op !== 'is_empty' && op !== 'is_not_empty' && (value === undefined || value === null || value === '')) {
    return null
  }
  return { field, op, value, fieldDef: fields.find((f) => f.name === field) }
}

/** 判定单行是否匹配完成标志（ctx 为 null 时恒 false）.
 *
 * 类型分派与无值直通统一委托 fieldOps.matchValueCondition（与筛选契约同一套语义）；
 * multiselect 在委托前先经 formatMultiSelectValue 归一（兼容逗号分隔串）。
 */
export function isDoneRow(row: RowResponse, ctx: DoneCtx | null): boolean {
  if (!ctx) return false
  let raw = row[ctx.field]
  const ft = ctx.fieldDef?.field_type
  if (ft === 'multiselect' || ft === 'multi_select') {
    raw = formatMultiSelectValue(raw)
  }
  return matchValueCondition(raw, ctx.op, ctx.value, ctx.fieldDef)
}

/** 计算「勾选/取消完成」应写入 done_field 的新值.
 *
 * - 勾选（当前未完成）：写入配置的 done_value（multiselect 归一为数组）
 * - 取消（当前已完成）：boolean 取反；multiselect 从行值中移除匹配项（移空则清空）；
 *   select/text 等其余类型清空（null）
 * - 日期类字段（date/datetime）+ 无值操作符（is_empty/is_not_empty）：
 *   「有日期即完成 / 有日期即未完成」双向语义明确 —— 勾选与取消时写入/清空今天，
 *   date 用 'YYYY-MM-DD'，datetime 用 'YYYY-MM-DD HH:mm:ss'，确保清空后重新勾选可往返
 * - 其余类型 + 无值操作符：没有确定的对侧值，返回 undefined 哨兵，调用方据此禁用该交互
 */
export function buildDoneToggleValue(row: RowResponse, ctx: DoneCtx): unknown {
  const ft = ctx.fieldDef?.field_type

  if (ctx.op === 'is_empty' || ctx.op === 'is_not_empty') {
    if (ft === 'date' || ft === 'datetime') {
      const today = ft === 'datetime' ? dayjs().format('YYYY-MM-DD HH:mm:ss') : dayjs().format('YYYY-MM-DD')
      // 目标状态与当前相反：is_not_empty 的完成态是"有日期"，is_empty 的完成态是"空"
      // → 未完成勾选：写入 is_not_empty 的完成值（今天）或 is_empty 的完成值（null）
      // → 已完成取消：反向写回
      if (isDoneRow(row, ctx)) return ctx.op === 'is_empty' ? today : null
      return ctx.op === 'is_empty' ? null : today
    }
    return undefined
  }

  if (isDoneRow(row, ctx)) {
    if (ft === 'boolean') return !ctx.value
    if (ft === 'multiselect' || ft === 'multi_select') {
      const rowVals = formatMultiSelectValue(row[ctx.field])
      const cfgVals = (Array.isArray(ctx.value) ? ctx.value : [ctx.value]).map(String)
      const options = ctx.fieldDef?.config ? extractSelectOptions(ctx.fieldDef.config) : []
      const toValue = (s: string): string => {
        const hit = options.find((o) => o.value === s || o.label === s)
        return hit ? hit.value : s
      }
      const cfgSet = new Set(cfgVals.map(toValue))
      const remain = rowVals.filter((v) => !cfgSet.has(toValue(v)))
      return remain.length ? remain : null
    }
    return null
  }

  if (ft === 'multiselect' || ft === 'multi_select') {
    return Array.isArray(ctx.value) ? ctx.value : [ctx.value]
  }
  return ctx.value
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

/** 对一列卡片应用完整排序：未完成在前、已完成置底；未完成内部按紧急置顶 + card_sort_field + view_sortings；
 * 已完成内部按完成时间倒序（后完成在顶部）：优先用 done_field 的日期值，其次用 updated_at，最后用 created_at 倒序 */
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
  const doneCtx = resolveDoneCtx(opts, fields)
  // done_field 是否为日期类型 —— 已完成内部排序时优先用它作为"完成时间"
  const doneFieldDef = doneCtx?.fieldDef
  const doneIsDate = !!doneFieldDef && ['date', 'datetime', 'timestamp'].includes(doneFieldDef.field_type)

  // 把所有排序规则拼成有序列表
  // 优先级（未完成内部）：紧急置顶 > card_sort_field > 级联 view_sortings > 优先级权重 > 创建时间倒序
  const sortKeys: Array<{ field_name: string; direction: 'asc' | 'desc' }> = []
  if (cardSortField) sortKeys.push({ field_name: cardSortField, direction: cardSortDir })
  for (const s of viewSortings) {
    if (s.field_name === cardSortField) continue // 去重
    sortKeys.push(s)
  }

  /** 从行取完成排序用的时间戳：done_field 日期值 > updated_at > created_at */
  const getDoneTime = (r: RowResponse): number => {
    if (doneIsDate) {
      const v = r[doneCtx!.field]
      if (v !== null && v !== undefined) {
        const t = new Date(String(v)).getTime()
        if (!Number.isNaN(t)) return t
      }
    }
    const u = (r.updated_at as string | undefined) || ''
    if (u) {
      const t = new Date(u).getTime()
      if (!Number.isNaN(t)) return t
    }
    const c = (r.created_at as string | undefined) || ''
    if (c) {
      const t = new Date(c).getTime()
      if (!Number.isNaN(t)) return t
    }
    return 0
  }

  return [...rows].sort((a, b) => {
    const aDone = isDoneRow(a, doneCtx)
    const bDone = isDoneRow(b, doneCtx)

    // 0) 未完成 vs 已完成：未完成（0）在前，已完成（1）在后
    if (aDone !== bDone) return aDone ? 1 : -1

    // 已完成内部：后完成的排顶部（完成时间倒序）
    if (aDone) {
      return getDoneTime(b) - getDoneTime(a)
    }

    // --- 以下为未完成内部的排序规则 ---

    // 1) 紧急置顶（逾期 > 紧急 > 正常）
    if (pinUrgent) {
      const au = getUrgencyRank(a, dueDateField, urgentThreshold)
      const bu = getUrgencyRank(b, dueDateField, urgentThreshold)
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

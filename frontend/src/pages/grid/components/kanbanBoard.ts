/** 看板纯逻辑层 — 卡片排序、紧急级别、分组聚合（与 UI 解耦，可独立单测）.
 *
 * 从 KanbanView.tsx 抽取：
 * - getUrgencyRank / getPriorityRank / compareField / sortKanbanCards：原样迁移
 * - resolveGroupField / groupKanbanColumns：分组聚合逻辑（link/multi_select/select 按首值标签分列）
 */

import type { RowResponse, Field } from '@/api'
import { extractSelectOptions } from './fieldOps'
import { parseDate, daysFromToday } from './dateUtils'
import { getSelectLabel, getLinkFirstLabel, getMultiSelectFirstLabel } from './fieldValueFormat'

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

  // 把所有排序规则拼成有序列表
  // 优先级：紧急置顶 > card_sort_field > 级联 view_sortings > 优先级权重 > 创建时间倒序
  const sortKeys: Array<{ field_name: string; direction: 'asc' | 'desc' }> = []
  if (cardSortField) sortKeys.push({ field_name: cardSortField, direction: cardSortDir })
  for (const s of viewSortings) {
    if (s.field_name === cardSortField) continue // 去重
    sortKeys.push(s)
  }

  return [...rows].sort((a, b) => {
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

  const makeCol = (key: string, title: string, list: RowResponse[]) => {
    const sorted = sortKanbanCards(list, fields, opts, sortings)
    let urgentCount = 0
    if (dueDateField) {
      for (const r of sorted) {
        const dueDate = parseDate(r[dueDateField])
        if (!dueDate) continue
        const dl = daysFromToday(dueDate)
        if (dl < 0 || dl <= urgentThreshold) urgentCount++
      }
    }
    cols.push({ key, title, rows: sorted, urgentCount })
  }

  if (!groupField) {
    // 无分组 → 单列
    makeCol('all', '全部', rows)
    return cols
  }

  const groups = new Map<string, RowResponse[]>()
  for (const r of rows) {
    const key = groupKeyForRow(r, groupField, groupFieldDef)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(r)
  }

  for (const [title, list] of groups) {
    makeCol(title, title, list)
  }

  return cols
}

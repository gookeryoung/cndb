/** 字段值格式化工具 —— 根据字段类型把 API 返回的原始值转为前端可显示字符串.
 *
 * 来源：从 KanbanView / GridCell 抽取的公共逻辑，统一 Kanban / Calendar / Gantt / WBS 视图的
 * 字段值渲染行为（link 字段返回 [{id, value}] 数组，multi_select 返回数组，
 * 直接 String() 会得到 "[object Object]"）.
 */

import { extractSelectOptions } from './fieldOps'
import type { Field, RowResponse } from '@/api'

// ── link 字段 ──────────────────────────────────────────

/** 从目标表字段列表中挑出适合做"行标签"的字段名（link 下拉选项展示用）.
 *
 * 优先级：is_primary 的 text 字段 → 第一个 text 字段 → null（调用方回退 #id）。
 * longtext 内容往往过长，不参与选择。
 */
export function pickLinkLabelFieldName(fields: Field[]): string | null {
  const textFields = fields.filter((f) => f.field_type === 'text' && !f.trashed)
  const primary = textFields.find((f) => f.is_primary)
  return (primary ?? textFields[0])?.name ?? null
}

/** 用目标表行数据构造 link 下拉选项的可读标签.
 *
 * 优先取 labelField 对应的业务值；无 labelField / 值为空 / 值为对象时回退 `#id`。
 */
export function buildLinkRowLabel(row: RowResponse, labelField?: string | null): string {
  if (labelField) {
    const v = (row as Record<string, unknown>)[labelField]
    if (v !== null && v !== undefined && v !== '' && typeof v !== 'object') {
      return String(v)
    }
  }
  return `#${row.id}`
}

/** 把 link 字段的 API 返回值（[{id, value}]）展平为可读字符串数组. */
export function formatLinkValue(value: unknown): string[] {
  if (!value) return []
  if (Array.isArray(value)) {
    return value
      .map((item: Record<string, unknown>) => {
        if (item && typeof item === 'object') {
          return String(item.value ?? item.label ?? item.id ?? '')
        }
        return String(item)
      })
      .filter(Boolean)
  }
  if (value && typeof value === 'object') {
    const o = value as Record<string, unknown>
    const v = o.value ?? o.label ?? o.id ?? ''
    return [String(v)]
  }
  return [String(value)]
}

/** 解析 link 字段值用于分组键提取 —— 取第一个 link 的 value. */
export function getLinkFirstLabel(value: unknown): string {
  const labels = formatLinkValue(value)
  return labels.length > 0 ? labels[0] : ''
}

// ── multi_select 字段 ─────────────────────────────────

/** 把 multiselect 字段值（逗号分隔字符串或数组）解析为标签数组. */
export function formatMultiSelectValue(value: unknown): string[] {
  if (!value) return []
  if (Array.isArray(value)) return value.map((v) => String(v)).filter(Boolean)
  return String(value)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 解析 multiselect 字段值用于分组键 —— 取第一个值. */
export function getMultiSelectFirstLabel(value: unknown): string {
  const labels = formatMultiSelectValue(value)
  return labels.length > 0 ? labels[0] : ''
}

// ── select 字段 ────────────────────────────────────────

/** 解析 select 字段的原始值为可读标签. */
export function getSelectLabel(field: Field, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  const options = extractSelectOptions(field.config)
  if (!options.length) return String(value)
  const strVal = String(value)
  const found = options.find((o) => o.value === strVal)
  return found ? found.label : strVal
}

// ── attachment / image 字段 ─────────────────────────────

/** 从 attachment / image 类型字段值里提取第一个可用 URL.
 *
 * 后端可能返回：
 * - 单个 URL string（以 http 或 / 开头）
 * - 单对象 { url: "...", value: "..." }
 * - 数组 [obj1, obj2, ...]（多附件场景取第一个）
 * - 其他情况返回 null
 */
export function extractImageUrl(v: unknown): string | null {
  if (!v) return null
  if (typeof v === 'string') {
    if (v.startsWith('http') || v.startsWith('/')) return v
    return null
  }
  if (Array.isArray(v)) {
    const first = v[0]
    return extractImageUrl(first)
  }
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    const url = (o.url as string) || (o.value as string) || null
    if (url && (url.startsWith('http') || url.startsWith('/'))) return url
  }
  return null
}

// ── 通用入口 ──────────────────────────────────────────

/** 通用值格式化入口：根据字段类型把 row[fieldName] 转为可显示字符串. */
export function formatFieldDisplayValue(field: Field, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''

  switch (field.field_type) {
    case 'select':
      return getSelectLabel(field, value)

    case 'multi_select':
    case 'multiselect':
      return formatMultiSelectValue(value).join(', ')

    case 'link':
      return formatLinkValue(value).join(', ')

    case 'boolean':
      return value ? '是' : '否'

    case 'date':
    case 'datetime':
    case 'timestamp':
      return String(value)

    default:
      return String(value)
  }
}

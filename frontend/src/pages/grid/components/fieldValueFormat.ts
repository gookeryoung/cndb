/** 字段值格式化工具 —— 根据字段类型把 API 返回的原始值转为前端可显示字符串.
 *
 * 来源：从 KanbanView / GridCell 抽取的公共逻辑，统一 Gallery / Kanban / Calendar 视图的
 * 字段值渲染行为（link 字段返回 [{id, value}] 数组，multi_select 返回数组，
 * 直接 String() 会得到 "[object Object]"）.
 */

import type { Field } from '@/api'

// ── link 字段 ──────────────────────────────────────────

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
  const options = (field.config as Record<string, unknown> | undefined)?.options as
    | Array<Record<string, unknown>>
    | undefined
  if (!options) return String(value)
  const strVal = String(value)
  const found = options.find((o) => String(o.value ?? o.name ?? '') === strVal)
  return found ? String(found.label ?? found.value ?? found.name ?? value) : strVal
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

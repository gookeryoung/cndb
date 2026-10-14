/** 单元格取值归一化工具 —— 编辑器草稿 ↔ 后端 schema 的互转.
 *
 * 供 GridCell 展示/编辑两态与 GridPage 行内新增/整行编辑共用，
 * 保证三处入口的取值语义一致。
 */

import type { Field } from '@/api'
import dayjs, { Dayjs } from 'dayjs'

// ─────────────── 辅助函数 ───────────────

/** 只读字段（系统自动维护 / 无物理列实时解析）不能 inline 编辑 */
export function isReadonlyField(field: Field): boolean {
  const readonly = new Set(['auto_id', 'created_time', 'updated_time', 'created_by', 'updated_by', 'formula', 'lookup'])
  return readonly.has(field.field_type)
}

/** 进入编辑态前：把后端值转换成编辑器能吃的 JS 值 */
export function normalizeValueForEdit(value: unknown, field: Field): unknown {
  if (value === null || value === undefined) {
    if (field.field_type === 'boolean') return false
    if (['number', 'decimal', 'float', 'percentage', 'timestamp'].includes(field.field_type)) return null
    if (['multi_select', 'multiselect'].includes(field.field_type)) return []
    if (field.field_type === 'link') return []  // link 从 [{id, value}] 转为空数组，由 ExtractLinkIds 在 EditCell 内部处理
    if (field.field_type === 'attachment' || field.field_type === 'image') return []
    return ''
  }
  if (field.field_type === 'link') {
    // API 返回 [{id, value}]，编辑器消费纯 id 数组
    return extractLinkIds(value)
  }
  if (field.field_type === 'attachment' || field.field_type === 'image') {
    // 后端存 JSON 字符串，前端编辑器消费 AttachmentFile[]
    if (Array.isArray(value)) return value
    try { return JSON.parse(String(value || '[]')) } catch { return [] }
  }
  if (field.field_type === 'date' || field.field_type === 'datetime') {
    return value
  }
  return value
}

/** 从 link 字段 API 返回值中提取纯 id 数组. */
export function extractLinkIds(value: unknown): number[] {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) {
    return value.map((item: any) => {
      if (typeof item === 'number') return item
      if (item && typeof item === 'object') return item.id
      return Number(item)
    }).filter((n: number) => !Number.isNaN(n) && n > 0)
  }
  if (typeof value === 'number') return [value]
  return []
}

/** 离开编辑态保存前：把编辑器的草稿值转换成后端 schema 需要的格式 */
export function finalizeValueFromEdit(draft: unknown, field: Field): unknown {
  const ft = field.field_type
  if (draft === '' || draft === null || draft === undefined) {
    // 空值统一 null 让后端处理
    if (field.required) return null
    return null
  }
  switch (ft) {
    case 'number':
    case 'decimal':
    case 'float':
    case 'percentage':
    case 'timestamp': {
      const n = typeof draft === 'number' ? draft : Number(String(draft).trim())
      return Number.isNaN(n) ? null : n
    }
    case 'multi_select':
    case 'multiselect': {
      return Array.isArray(draft) ? draft : []
    }
    case 'date':
    case 'datetime': {
      // 编辑器给的是 dateStr 或 Dayjs
      if (typeof draft === 'string') return draft
      if (dayjs.isDayjs(draft as Dayjs)) return (draft as Dayjs).format(ft === 'date' ? 'YYYY-MM-DD' : 'YYYY-MM-DD HH:mm:ss')
      return draft
    }
    case 'boolean':
      return Boolean(draft)
    case 'link': {
      // 如果用户直接粘了 JSON 尝试 parse
      if (typeof draft === 'string') {
        try { return JSON.parse(draft) } catch { return draft }
      }
      return draft
    }
    default:
      return draft
  }
}

/**
 * 导出的字段值归一化：把编辑器草稿值转成后端接受的格式。
 * 供 GridPage 行内新增/整行编辑在保存时统一复用。
 */
export function finalizeCellValue(draft: unknown, field: Field): unknown {
  return finalizeValueFromEdit(draft, field)
}

/**
 * 导出的字段值归一化（编辑态）：把后端值转成编辑器可消费的草稿。
 * 供 GridPage 行内新增/整行编辑初始化草稿时复用（与单元格双击编辑的转换保持一致）。
 */
export function normalizeCellValueForEdit(value: unknown, field: Field): unknown {
  return normalizeValueForEdit(value, field)
}

/**
 * 判断草稿是否为空（不参与提交）。
 * 空串 / null / undefined / 空数组 视为空。
 */
export function isBlankCellValue(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return true
  if (Array.isArray(v)) return v.length === 0
  return false
}

/**
 * 该字段是否在行内编辑中可编辑（与展示/单元格双击判定一致）。
 */
export function isEditableInlineField(field: Field): boolean {
  return !isReadonlyField(field) && !field.trashed
}

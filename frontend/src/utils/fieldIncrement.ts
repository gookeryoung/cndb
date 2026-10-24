/** 单行文本自动编号 —— 字段判定 / 示例编号 / 新增行提示的单一真相源.
 *
 * 自动编号（config.default_mode=auto_increment）的值由后端建行时按库内
 * 已有数据推算，前端不预填；新增行里必须以只读提示展示，避免用户误以为
 * 该字段需要手填或字段丢失.
 */

import type { Field } from '@/api'

type IncrementField = Pick<Field, 'field_type' | 'config'>

/** 字段是否为单行文本自动编号（值与唯一性口径同后端 TextFieldConfig） */
export function isAutoIncrementField(field: IncrementField): boolean {
  return field.field_type === 'text' && field.config?.default_mode === 'auto_increment'
}

/** 由自动编号 config 拼出示例编号（如 PRJ-0001），供字段列表备注 / 新增行提示共用 */
export function formatIncrementExample(config: Record<string, unknown> | undefined): string {
  const prefix = String(config?.increment_prefix ?? '')
  const paddingNum = Number(config?.increment_padding ?? 4)
  const padding = Number.isFinite(paddingNum) ? Math.max(0, Math.min(10, Math.trunc(paddingNum))) : 4
  const startNum = Number(config?.increment_start ?? 1)
  const start = Number.isFinite(startNum) ? Math.max(0, Math.trunc(startNum)) : 1
  return `${prefix}${String(start).padStart(padding, '0')}`
}

/** 新增行 / 新建行抽屉里自动编号字段的提示文案（不预填，保存后由后端生成） */
export function autoIncrementHint(field: IncrementField): string {
  return `保存时自动生成（如 ${formatIncrementExample(field.config)}）`
}

/** 数字字段取值范围的符号标签 —— 唯一真相源.
 *
 * `number` / `float`（含历史别名 `decimal`）的 `config.min` / `config.max` 由后端
 * 字段类型强校验（见 `field_types/number.py`），网格列头与字段管理列表统一用本模块
 * 生成紧凑符号文案：
 *
 * - 双边界：`0–100`
 * - 只有下限：`≥0`
 * - 只有上限：`≤100`
 *
 * 其它类型不生成标签：百分比（`percentage`）的 0~1 值域是类型隐式约束、配置里没有
 * 可展示的 min/max；文本 / 日期等没有范围配置。
 */

import type { Field } from '@/api'

/** 配置了 min/max 且后端会真正校验的数值类型 */
const RANGE_FIELD_TYPES: ReadonlySet<string> = new Set(['number', 'float', 'decimal'])

export interface FieldRangeBadge {
  /** 紧凑符号文案：`0–100` / `≥0` / `≤100` */
  text: string
  /** 悬停提示：取值范围（含边界） */
  tooltip: string
}

/** 读取边界值：只有有限数字才算配置了边界（`null` / `''` / NaN 视为不限） */
function readBound(raw: unknown): number | null {
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null
}

/** 生成字段取值范围标签；无范围配置返回 null（调用方据此不渲染） */
export function fieldRangeBadge(
  field: Pick<Field, 'field_type'> & { config?: Record<string, unknown> },
): FieldRangeBadge | null {
  if (!RANGE_FIELD_TYPES.has(field.field_type)) return null
  const config = field.config ?? {}
  const min = readBound(config.min)
  const max = readBound(config.max)
  if (min === null && max === null) return null

  const low = min === null ? '' : String(min)
  const high = max === null ? '' : String(max)
  const text = min !== null && max !== null
    ? `${low}–${high}`
    : min !== null
      ? `≥${low}`
      : `≤${high}`
  const tooltip = `取值范围 ${min !== null ? low : '不限'} ~ ${max !== null ? high : '不限'}（含边界）`
  return { text, tooltip }
}

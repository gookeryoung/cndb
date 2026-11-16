/** 数字字段取值范围符号标签（fieldRangeBadge）纯函数矩阵.
 *
 * 覆盖：双边界 / 单边界 / 0 值边界（不得被当成未配置）/ 小数 /
 * 历史别名 decimal / 非数值类型不生成 / 非法配置（NaN、字符串、缺 config）。
 */

import { describe, expect, it } from 'vitest'
import { fieldRangeBadge } from './fieldRange'

const numberField = (config?: Record<string, unknown>) =>
  ({ field_type: 'number', config }) as const

describe('fieldRangeBadge 符号文案', () => {
  it('双边界输出「下限–上限」', () => {
    expect(fieldRangeBadge(numberField({ min: 0, max: 100 }))).toEqual({
      text: '0–100',
      tooltip: '取值范围 0 ~ 100（含边界）',
    })
  })

  it('只有下限输出 ≥，只有上限输出 ≤', () => {
    expect(fieldRangeBadge(numberField({ min: 0 }))?.text).toBe('≥0')
    expect(fieldRangeBadge(numberField({ max: 100 }))?.text).toBe('≤100')
  })

  it('工具提示对未配置的一侧写「不限」', () => {
    expect(fieldRangeBadge(numberField({ min: 5 }))?.tooltip).toBe('取值范围 5 ~ 不限（含边界）')
    expect(fieldRangeBadge(numberField({ max: 5 }))?.tooltip).toBe('取值范围 不限 ~ 5（含边界）')
  })

  it('0 是有效边界（不能被当成未配置）', () => {
    expect(fieldRangeBadge(numberField({ min: 0, max: 0 }))?.text).toBe('0–0')
  })

  it('小数边界原样输出，不做补零', () => {
    expect(fieldRangeBadge(numberField({ min: 0.5, max: 99.9 }))?.text).toBe('0.5–99.9')
    expect(fieldRangeBadge({ field_type: 'float', config: { min: -1, max: 1 } })?.text).toBe('-1–1')
  })

  it('历史别名 decimal 与 float 同样生效', () => {
    expect(fieldRangeBadge({ field_type: 'decimal', config: { min: 1, max: 9 } })?.text).toBe('1–9')
    expect(fieldRangeBadge({ field_type: 'float', config: { max: 9 } })?.text).toBe('≤9')
  })
})

describe('fieldRangeBadge 不生成标签的情形', () => {
  it('无 config / 无 min/max 返回 null', () => {
    expect(fieldRangeBadge(numberField())).toBeNull()
    expect(fieldRangeBadge(numberField({}))).toBeNull()
    expect(fieldRangeBadge(numberField({ min: null, max: null }))).toBeNull()
  })

  it('非数值类型即使带 min/max 也不生成', () => {
    expect(fieldRangeBadge({ field_type: 'percentage', config: { min: 0, max: 1 } })).toBeNull()
    expect(fieldRangeBadge({ field_type: 'text', config: { min: 0, max: 1 } })).toBeNull()
  })

  it('非有限数字 / 字符串边界视为未配置', () => {
    expect(fieldRangeBadge(numberField({ min: Number.NaN, max: Number.POSITIVE_INFINITY }))).toBeNull()
    expect(fieldRangeBadge(numberField({ min: '0', max: '100' }))).toBeNull()
  })
})

/** chartLinkage 纯函数测试 — 双轴主次值联动公式（ADR 0056 D2 / D3）. */

import { describe, expect, it } from 'vitest'
import { hasBase, linkGrowthFromValue, linkValueFromGrowth } from './chartLinkage'

describe('linkValueFromGrowth（填次值联动主值）', () => {
  it('主值ᵢ = 主值ᵢ₋₁ × (1 + 次值/100)，一位小数', () => {
    expect(linkValueFromGrowth(285, 14)).toBe(324.9)
    expect(linkValueFromGrowth(132, 19.7)).toBe(158)
    expect(linkValueFromGrowth(100, 33.33)).toBe(133.3)
  })

  it('上年基数缺失 / 0 / 负数 / 非有限 → 不联动（null）', () => {
    expect(linkValueFromGrowth(null, 10)).toBeNull()
    expect(linkValueFromGrowth(0, 10)).toBeNull()
    expect(linkValueFromGrowth(-5, 10)).toBeNull()
    expect(linkValueFromGrowth(Number.NaN, 10)).toBeNull()
  })

  it('次值非有限 → 不联动', () => {
    expect(linkValueFromGrowth(100, Number.NaN)).toBeNull()
    expect(linkValueFromGrowth(100, Number.POSITIVE_INFINITY)).toBeNull()
  })
})

describe('linkGrowthFromValue（改主值反向重算次值）', () => {
  it('次值 = (主值/上年 − 1) × 100，一位小数（与渲染端口径一致）', () => {
    expect(linkGrowthFromValue(324.9, 285)).toBe(14)
    expect(linkGrowthFromValue(158, 132)).toBe(19.7)
    expect(linkGrowthFromValue(100, 150)).toBe(-33.3)
  })

  it('上年基数缺失 / 0 / 负数 → 不联动（null）', () => {
    expect(linkGrowthFromValue(120, null)).toBeNull()
    expect(linkGrowthFromValue(120, 0)).toBeNull()
    expect(linkGrowthFromValue(120, -1)).toBeNull()
  })

  it('主值非有限 → 不联动', () => {
    expect(linkGrowthFromValue(Number.NaN, 100)).toBeNull()
  })
})

describe('hasBase', () => {
  it('仅正的有限数为有效基数', () => {
    expect(hasBase(1)).toBe(true)
    expect(hasBase(null)).toBe(false)
    expect(hasBase(0)).toBe(false)
    expect(hasBase(Number.NaN)).toBe(false)
  })
})

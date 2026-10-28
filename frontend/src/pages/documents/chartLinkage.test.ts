/** chartLinkage 纯函数测试 — 双轴主次值联动公式（ADR 0056 D2 / D3）. */

import { describe, expect, it } from 'vitest'
import { growthLinkedDisplay, hasBase, linkGrowthFromValue, linkValueFromGrowth } from './chartLinkage'

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

describe('growthLinkedDisplay（默认联动态显示值，ADR 0059 C2）', () => {
  it('次值留空且基数可推算 → 联动态，显示推算值（一位小数）', () => {
    expect(growthLinkedDisplay(null, 324.9, 285)).toEqual({ linked: true, display: 14 })
    expect(growthLinkedDisplay(null, 158, 132)).toEqual({ linked: true, display: 19.7 })
    expect(growthLinkedDisplay(null, 100, 150)).toEqual({ linked: true, display: -33.3 })
  })

  it('次值已有显式值 → 非联动态，显示原值', () => {
    expect(growthLinkedDisplay(12.5, 324.9, 285)).toEqual({ linked: false, display: 12.5 })
  })

  it('基数缺失 / 0 / 负数 / 主值留空 → 非联动态', () => {
    expect(growthLinkedDisplay(null, 120, null)).toEqual({ linked: false, display: null })
    expect(growthLinkedDisplay(null, 120, 0)).toEqual({ linked: false, display: null })
    expect(growthLinkedDisplay(null, 120, -1)).toEqual({ linked: false, display: null })
    expect(growthLinkedDisplay(null, null, 100)).toEqual({ linked: false, display: null })
  })
})

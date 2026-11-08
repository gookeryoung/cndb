/** 视口自适应缩放距离单测（ADR 0103 C3）：按视口宽高比取较小视场角，只缩放不改方位. */

import { describe, expect, it } from 'vitest'
import { fitDistance } from './PreviewCanvas'

const HALF_V = (45 * Math.PI) / 360
const BASE = (10 * 1.6) / Math.tan(HALF_V)

describe('fitDistance', () => {
  it('宽视口（aspect > 1）由竖直视场角决定距离', () => {
    expect(fitDistance(45, 2, 10)).toBeCloseTo(BASE, 6)
  })

  it('窄视口（aspect < 1）由水平视场角决定距离，距离相应变大', () => {
    const narrow = fitDistance(45, 0.5, 10)
    expect(narrow).toBeGreaterThan(fitDistance(45, 2, 10))
    expect(narrow).toBeCloseTo((10 * 1.6) / Math.tan(Math.atan(Math.tan(HALF_V) * 0.5)), 6)
  })

  it('半径下限为 1，退化包围盒不会产生零距离', () => {
    expect(fitDistance(45, 1, 0)).toBeCloseTo(fitDistance(45, 1, 1), 6)
  })
})

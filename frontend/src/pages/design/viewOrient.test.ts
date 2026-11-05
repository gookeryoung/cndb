/** 视口定向常量表单测（ADR 0103 C3 / D11）：七向方位、up 与视线不共线. */

import { describe, expect, it } from 'vitest'
import { VIEW_PRESETS, viewPreset } from './viewOrient'

describe('VIEW_PRESETS', () => {
  it('覆盖七向定向且术语对齐机械制图惯例', () => {
    expect(VIEW_PRESETS.map(preset => preset.label)).toEqual([
      '主视', '俯视', '仰视', '左视', '右视', '后视', '等轴测',
    ])
    expect(VIEW_PRESETS.map(preset => preset.key)).toEqual([
      'front', 'top', 'bottom', 'left', 'right', 'back', 'iso',
    ])
  })

  it('方向向量均为单位向量（等轴测归一前允许非单位，其余须精确）', () => {
    for (const preset of VIEW_PRESETS.filter(item => item.key !== 'iso')) {
      const length = Math.hypot(...preset.dir)
      expect(length).toBeCloseTo(1, 6)
    }
    expect(Math.hypot(...viewPreset('iso')!.dir)).toBeGreaterThan(1)
  })

  it('up 与视线方向不共线（避免 lookAt 退化）', () => {
    for (const preset of VIEW_PRESETS) {
      const dot = preset.dir[0] * preset.up[0] + preset.dir[1] * preset.up[1] + preset.dir[2] * preset.up[2]
      expect(Math.abs(dot)).toBeLessThan(0.99)
    }
  })

  it('Z-up 世界：俯视从 +Z 看向原点、主视从 −Y 看向 +Y', () => {
    expect(viewPreset('top')!.dir).toEqual([0, 0, 1])
    expect(viewPreset('bottom')!.dir).toEqual([0, 0, -1])
    expect(viewPreset('front')!.dir).toEqual([0, -1, 0])
    expect(viewPreset('back')!.dir).toEqual([0, 1, 0])
    expect(viewPreset('left')!.dir).toEqual([-1, 0, 0])
    expect(viewPreset('right')!.dir).toEqual([1, 0, 0])
  })

  it('未知 key 返回 undefined（调用方静默忽略）', () => {
    expect(viewPreset('side')).toBeUndefined()
  })
})

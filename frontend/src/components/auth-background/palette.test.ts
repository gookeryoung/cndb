import { afterEach, describe, expect, it, vi } from 'vitest'

import { createRandom, particleBudget, readPalette, withAlpha } from './palette'

function mockComputedStyle(values: Record<string, string>) {
  return vi.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) => values[name] ?? '',
  } as CSSStyleDeclaration)
}

describe('withAlpha', () => {
  it('解析 6 位与 3 位十六进制', () => {
    expect(withAlpha('#3b82f6', 0.5)).toBe('rgba(59, 130, 246, 0.5)')
    expect(withAlpha('#fff', 1)).toBe('rgba(255, 255, 255, 1)')
    expect(withAlpha('#abcd', 0.25)).toBe('rgba(170, 187, 204, 0.25)')
  })

  it('解析 rgb / rgba', () => {
    expect(withAlpha('rgb(1, 2, 3)', 0.4)).toBe('rgba(1, 2, 3, 0.4)')
    expect(withAlpha('rgba(10, 20, 30, 0.8)', 0.2)).toBe('rgba(10, 20, 30, 0.2)')
  })

  it('夹取透明度并容忍非法输入', () => {
    expect(withAlpha('#000000', 5)).toBe('rgba(0, 0, 0, 1)')
    expect(withAlpha('#000000', -1)).toBe('rgba(0, 0, 0, 0)')
    expect(withAlpha('#000000', Number.NaN)).toBe('rgba(0, 0, 0, 0)')
    expect(withAlpha('color-mix(in srgb, red, blue)', 0.5)).toBe('color-mix(in srgb, red, blue)')
  })
})

describe('readPalette', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('读取三个主题变量', () => {
    mockComputedStyle({
      '--cn-brand-color': '#3b82f6',
      '--cn-text-primary': '#1f2937',
      '--cn-bg-page': '#f5f7fa',
    })
    expect(readPalette()).toEqual({
      brand: '#3b82f6',
      text: '#1f2937',
      bg: '#f5f7fa',
    })
  })

  it('任一变量缺失返回 null', () => {
    mockComputedStyle({ '--cn-brand-color': '#3b82f6' })
    expect(readPalette()).toBeNull()
  })

  it('变量为空字符串也视为失败', () => {
    mockComputedStyle({
      '--cn-brand-color': '',
      '--cn-text-primary': '#000',
      '--cn-bg-page': '#fff',
    })
    expect(readPalette()).toBeNull()
  })
})

describe('createRandom', () => {
  it('同一种子序列一致', () => {
    const a = createRandom(42)
    const b = createRandom(42)
    expect([a(), a(), a()]).toEqual([b(), b(), b()])
  })

  it('输出落在 0..1', () => {
    const random = createRandom(7)
    for (let i = 0; i < 20; i++) {
      const value = random()
      expect(value).toBeGreaterThanOrEqual(0)
      expect(value).toBeLessThan(1)
    }
  })
})

describe('particleBudget', () => {
  it('移动端在桌面基础上降档', () => {
    const desktop = particleBudget(1_000_000, 120, false, 10000)
    const mobile = particleBudget(1_000_000, 120, true, 10000)
    expect(mobile).toBeLessThan(desktop)
    expect(mobile).toBeGreaterThan(0)
  })

  it('不超过上限且不低于下限', () => {
    expect(particleBudget(10_000_000, 80, false, 10000)).toBe(80)
    expect(particleBudget(0, 80, false, 10000)).toBe(16)
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'

import { readPalette, withAlpha } from './palette'

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

  it('读取固定舞台的三个 auth token', () => {
    mockComputedStyle({
      '--cn-auth-accent': '#22d3ee',
      '--cn-auth-accent-alt': '#a855f7',
      '--cn-auth-ink': '#dbe4f3',
    })
    expect(readPalette()).toEqual({
      accent: '#22d3ee',
      accentAlt: '#a855f7',
      ink: '#dbe4f3',
    })
  })

  it('任一变量缺失返回 null', () => {
    mockComputedStyle({
      '--cn-auth-accent': '#22d3ee',
      '--cn-auth-ink': '#dbe4f3',
    })
    expect(readPalette()).toBeNull()
  })

  it('变量为空字符串也视为失败', () => {
    mockComputedStyle({
      '--cn-auth-accent': '#22d3ee',
      '--cn-auth-accent-alt': '',
      '--cn-auth-ink': '#dbe4f3',
    })
    expect(readPalette()).toBeNull()
  })
})

/** themeMix 单元测试 —— 注册表完整性、预乘 alpha 求值、变量解析与主题重算 */
import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MIX_REGISTRY, applyThemeMixVars, mixColor, parseColor } from './themeMix'

function stubColorMixSupport(supported: boolean) {
  vi.stubGlobal('CSS', { supports: () => supported })
}

beforeEach(() => {
  document.body.className = ''
  document.body.removeAttribute('style')
  document.documentElement.removeAttribute('style')
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.removeAttribute('style')
  document.documentElement.removeAttribute('style')
})

function setTokens(tokens: Record<string, string>) {
  for (const [name, value] of Object.entries(tokens)) {
    document.body.style.setProperty(name, value)
  }
}

describe('MIX_REGISTRY', () => {
  it('覆盖源码中出现的全部 --cn-mix-* 名称', () => {
    const root = path.resolve(process.cwd(), 'src')
    const css = fs.readFileSync(path.join(root, 'index.css'), 'utf-8')
    const used = new Set<string>()
    for (const m of css.matchAll(/--cn-mix-([a-z0-9-]+)/g)) used.add(m[1])

    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
          continue
        }
        if (!entry.name.endsWith('.tsx') && !entry.name.endsWith('.ts')) continue
        if (entry.name === 'themeMix.ts' || entry.name === 'themeMix.test.ts') continue
        const text = fs.readFileSync(full, 'utf-8')
        for (const m of text.matchAll(/--cn-mix-([a-z0-9-]+)/g)) used.add(m[1])
      }
    }
    walk(root)

    const missing = [...used].filter(name => !(name in MIX_REGISTRY))
    expect(missing).toEqual([])
  })

  it('每条规格的权重合计为 100', () => {
    for (const [name, spec] of Object.entries(MIX_REGISTRY)) {
      expect(spec.aPct + (spec.bPct ?? 0), name).toBe(100)
    }
  })
})

describe('parseColor', () => {
  it('解析 hex / rgb / transparent，并把 RGB 三元组按 rgb() 处理', () => {
    expect(parseColor('#fff')).toEqual({ r: 255, g: 255, b: 255, a: 1 })
    expect(parseColor('#1677ff80')?.a).toBeCloseTo(0.502, 3)
    expect(parseColor('rgb(1, 2, 3)')).toEqual({ r: 1, g: 2, b: 3, a: 1 })
    expect(parseColor('rgba(1, 2, 3, 0.5)')).toEqual({ r: 1, g: 2, b: 3, a: 0.5 })
    expect(parseColor('rgb(1 2 3 / 25%)')).toEqual({ r: 1, g: 2, b: 3, a: 0.25 })
    expect(parseColor('transparent')).toEqual({ r: 0, g: 0, b: 0, a: 0 })
    // --cn-shadow-color 是 "15 23 42" 三元组
    expect(parseColor('15 23 42')).toEqual({ r: 15, g: 23, b: 42, a: 1 })
  })

  it('展开 var() 与 fallback，读不到变量时用 fallback', () => {
    setTokens({ '--cn-brand-color': '#1677ff' })
    expect(parseColor('var(--cn-brand-color)')).toEqual({ r: 22, g: 119, b: 255, a: 1 })
    expect(parseColor('var(--cn-primary, #ff0000)')).toEqual({ r: 255, g: 0, b: 0, a: 1 })
    expect(parseColor('var(--missing)')).toBeNull()
  })
})

describe('mixColor', () => {
  it('原生支持时原样返回 color-mix()', () => {
    stubColorMixSupport(true)
    expect(mixColor('#22c55e', 10, 'transparent'))
      .toBe('color-mix(in srgb, #22c55e 10%, transparent)')
  })

  it('按预乘 alpha 插值：透明色不参与 RGB 拉低', () => {
    stubColorMixSupport(false)
    // 非预乘实现会得到 rgb(3, 20, 9)，预乘后保持原色相、仅降低 alpha
    expect(mixColor('#22c55e', 10, 'transparent')).toBe('rgba(34, 197, 94, 0.1)')
  })

  it('不透明混色输出 rgb()', () => {
    stubColorMixSupport(false)
    expect(mixColor('#000000', 50, '#ffffff')).toBe('rgb(128, 128, 128)')
  })

  it('变量无法解析时退回 color-mix() 表达式', () => {
    stubColorMixSupport(false)
    expect(mixColor('#1677ff', 16, 'var(--cn-bg-subtle)'))
      .toBe('color-mix(in srgb, #1677ff 16%, var(--cn-bg-subtle))')
  })
})

describe('applyThemeMixVars', () => {
  it('按当前主题变量写入全部 --cn-mix-* 字面量', () => {
    stubColorMixSupport(false)
    setTokens({
      '--cn-brand-color': '#1677ff',
      '--cn-bg-container': '#ffffff',
      '--cn-border': '#e5e7eb',
      '--cn-shadow-color': '15 23 42',
      '--cn-text-primary': '#111827',
    })

    applyThemeMixVars()

    const root = document.documentElement.style
    expect(root.getPropertyValue('--cn-mix-brand-color-12-bg-container')).toBe('rgb(227, 239, 255)')
    expect(root.getPropertyValue('--cn-mix-shadow-color-10-transparent')).toBe('rgba(15, 23, 42, 0.1)')
    expect(root.getPropertyValue('--cn-mix-primary-10-transparent')).toBe('rgba(22, 119, 255, 0.1)')
  })

  it('主题变量变化后重算，得到新的颜色', () => {
    stubColorMixSupport(false)
    setTokens({
      '--cn-brand-color': '#1677ff',
      '--cn-bg-container': '#ffffff',
    })
    applyThemeMixVars()
    const light = document.documentElement.style.getPropertyValue('--cn-mix-brand-color-12-bg-container')

    setTokens({ '--cn-brand-color': '#722ed1', '--cn-bg-container': '#1f1f1f' })
    applyThemeMixVars()
    const dark = document.documentElement.style.getPropertyValue('--cn-mix-brand-color-12-bg-container')

    expect(dark).not.toBe(light)
    expect(dark).toBe('rgb(41, 33, 52)')
  })

  it('现代内核直接使用原生 color-mix，不写入兜底变量', () => {
    stubColorMixSupport(true)
    applyThemeMixVars()
    expect(document.documentElement.style.getPropertyValue('--cn-mix-brand-color-12-bg-container')).toBe('')
  })
})

/**
 * theme 主题常量与持久化单元测试.
 *
 * 覆盖：THEME_MODES 完整性 / THEME_META 结构约束 / THEMES 全量覆盖 /
 * loadThemeMode（默认/legacy/合法/非法/异常）/ saveThemeMode / getThemeConfig。
 */

import fs from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  THEMES,
  THEME_META,
  THEME_MODES,
  THEME_PREFERENCES,
  AUTO_LIGHT,
  AUTO_DARK,
  getThemeConfig,
  loadThemeMode,
  saveThemeMode,
  FONT_SCALES,
  FONT_SCALE_META,
  DEFAULT_FONT_SETTINGS,
  DEFAULT_THEME_MODE,
  loadFontSettings,
  saveFontSettings,
} from './theme'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('THEME_MODES / THEME_META / THEMES 结构约束', () => {
  it('THEME_MODES 含 10 个主题且无重复', () => {
    expect(THEME_MODES).toHaveLength(10)
    expect(new Set(THEME_MODES).size).toBe(10)
  })

  it('每个主题都有完整元信息，id 与 key 一致，bodyClass 全局唯一', () => {
    const bodyClasses = THEME_MODES.map(m => THEME_META[m].bodyClass)
    for (const m of THEME_MODES) {
      const meta = THEME_META[m]
      expect(meta.id).toBe(m)
      expect(meta.label.length).toBeGreaterThan(0)
      expect(meta.description.length).toBeGreaterThan(0)
      expect(typeof meta.isDark).toBe('boolean')
    }
    expect(new Set(bodyClasses).size).toBe(10)
  })

  it('THEMES 覆盖全部主题且每个都非空对象', () => {
    for (const m of THEME_MODES) {
      expect(THEMES[m]).toBeTruthy()
      expect(Object.keys(THEMES[m]).length).toBeGreaterThan(0)
    }
  })

  it('深色主题标识正确（github-dark / midnight / oled 为深色）', () => {
    expect(THEME_META['github-dark'].isDark).toBe(true)
    expect(THEME_META.midnight.isDark).toBe(true)
    expect(THEME_META.oled.isDark).toBe(true)
    expect(THEME_META.modern.isDark).toBe(false)
  })
})

describe('THEME_PREFERENCES / auto 虚拟档（0066）', () => {
  it('偏好集合 = auto + 全部实际主题，且不含重复', () => {
    expect(THEME_PREFERENCES).toHaveLength(11)
    expect(THEME_PREFERENCES[0]).toBe('auto')
    expect(new Set(THEME_PREFERENCES).size).toBe(11)
    for (const m of THEME_MODES) expect(THEME_PREFERENCES).toContain(m)
  })

  it('auto 不进 THEME_META / THEMES：虚拟档无 bodyClass 与 ThemeConfig（C2）', () => {
    expect('auto' in THEME_META).toBe(false)
    expect('auto' in THEMES).toBe(false)
  })

  it('auto 落点为 github 同族：浅色 github-light、深色 github-dark（C4）', () => {
    expect(AUTO_LIGHT).toBe('github-light')
    expect(AUTO_DARK).toBe('github-dark')
    expect(THEME_META[AUTO_LIGHT].isDark).toBe(false)
    expect(THEME_META[AUTO_DARK].isDark).toBe(true)
  })

  it('默认主题偏好为 auto（C5）', () => {
    expect(DEFAULT_THEME_MODE).toBe('auto')
  })
})

describe('loadThemeMode', () => {
  it('无存储值时返回默认 auto（C5）', () => {
    expect(loadThemeMode()).toBe('auto')
  })

  it('兼容 legacy 值：light → modern，dark → github-dark', () => {
    localStorage.setItem('cndb_theme', 'light')
    expect(loadThemeMode()).toBe('modern')
    localStorage.setItem('cndb_theme', 'dark')
    expect(loadThemeMode()).toBe('github-dark')
  })

  it('合法主题值原样返回', () => {
    localStorage.setItem('cndb_theme', 'sakura')
    expect(loadThemeMode()).toBe('sakura')
  })

  it('auto 偏好值原样返回（C1：localStorage 存 auto 本身）', () => {
    localStorage.setItem('cndb_theme', 'auto')
    expect(loadThemeMode()).toBe('auto')
  })

  it('非法值回退默认 auto', () => {
    localStorage.setItem('cndb_theme', 'not-a-theme')
    expect(loadThemeMode()).toBe('auto')
  })

  it('localStorage 抛异常时回退默认 auto', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadThemeMode()).toBe('auto')
  })
})

describe('saveThemeMode / getThemeConfig', () => {
  it('saveThemeMode 写入 localStorage', () => {
    saveThemeMode('forest')
    expect(localStorage.getItem('cndb_theme')).toBe('forest')
  })

  it('saveThemeMode 可写入 auto 并往返一致（C1）', () => {
    saveThemeMode('auto')
    expect(localStorage.getItem('cndb_theme')).toBe('auto')
    expect(loadThemeMode()).toBe('auto')
  })

  it('getThemeConfig 返回对应主题配置并注入 Segmented 强对比 token', () => {
    // 保留原主题 token / components，且 Segmented 激活滑块=主题色、文字=反色
    const modern = getThemeConfig('modern')
    expect(modern.token).toMatchObject(THEMES.modern.token ?? {})
    expect(modern.components?.Segmented).toEqual({
      itemSelectedBg: '#3b82f6',
      itemSelectedColor: '#ffffff',
    })
    // 高亮度主题色（极夜黑青色）激活文字用深色保证可读
    const oled = getThemeConfig('oled')
    expect(oled.components?.Segmented).toEqual({
      itemSelectedBg: '#22d3ee',
      itemSelectedColor: '#0a0a0a',
    })
    expect(oled.components?.Switch).toEqual(THEMES.oled.components?.Switch)
  })
})

describe('深色主题 Segmented 激活项可读性', () => {
  it('标签文字色兜底不得命中激活项，避免灰字压主题色滑块', () => {
    const css = fs.readFileSync(path.resolve(process.cwd(), 'src/index.css'), 'utf-8')
    const offenders = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)]
      .flatMap(([, selector, body]) => {
        if (!/color\s*:\s*var\(--cn-text-secondary\)/.test(body)) return []
        return selector.split(',')
          .map(s => s.trim())
          .filter(s => s.includes('.ant-segmented-item-label') && !s.includes(':not(.ant-segmented-item-selected)'))
      })
    expect(offenders).toEqual([])
  })
})

describe('字体设置常量结构', () => {
  it('FONT_SCALES 含 4 个档位且 FONT_SCALE_META 全量覆盖、px 递增', () => {
    expect(FONT_SCALES).toHaveLength(4)
    expect(new Set(FONT_SCALES).size).toBe(4)
    for (const s of FONT_SCALES) {
      expect(FONT_SCALE_META[s].id).toBe(s)
      expect(FONT_SCALE_META[s].label.length).toBeGreaterThan(0)
      expect(FONT_SCALE_META[s].px).toBeGreaterThan(0)
    }
    const pxList = FONT_SCALES.map(s => FONT_SCALE_META[s].px)
    expect([...pxList].sort((a, b) => a - b)).toEqual(pxList)
  })

  it('默认字体设置为标准字号且不加粗', () => {
    expect(DEFAULT_FONT_SETTINGS).toEqual({ scale: 'standard', bold: false })
  })
})

describe('loadFontSettings', () => {
  it('无存储值时返回默认设置', () => {
    expect(loadFontSettings()).toEqual({ scale: 'standard', bold: false })
  })

  it('合法持久化值原样返回', () => {
    localStorage.setItem('cndb_font', JSON.stringify({ scale: 'large', bold: true }))
    expect(loadFontSettings()).toEqual({ scale: 'large', bold: true })
  })

  it('非法字号档位回退标准，bold 非布尔值回退默认', () => {
    localStorage.setItem('cndb_font', JSON.stringify({ scale: 'giant', bold: 'yes' }))
    expect(loadFontSettings()).toEqual({ scale: 'standard', bold: false })
  })

  it('JSON 损坏时回退默认设置', () => {
    localStorage.setItem('cndb_font', '{broken')
    expect(loadFontSettings()).toEqual({ scale: 'standard', bold: false })
  })

  it('localStorage 抛异常时回退默认设置', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadFontSettings()).toEqual({ scale: 'standard', bold: false })
  })
})

describe('saveFontSettings', () => {
  it('写入 localStorage 且与 loadFontSettings 往返一致', () => {
    saveFontSettings({ scale: 'huge', bold: true })
    expect(JSON.parse(localStorage.getItem('cndb_font') ?? '')).toEqual({ scale: 'huge', bold: true })
    expect(loadFontSettings()).toEqual({ scale: 'huge', bold: true })
  })
})

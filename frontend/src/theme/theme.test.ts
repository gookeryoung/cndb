/**
 * theme 主题常量与持久化单元测试.
 *
 * 覆盖：THEME_MODES 完整性 / THEME_META 结构约束 / THEMES 全量覆盖 /
 * loadThemeMode（默认/legacy/合法/非法/异常）/ saveThemeMode / getThemeConfig。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  THEMES,
  THEME_META,
  THEME_MODES,
  getThemeConfig,
  loadThemeMode,
  saveThemeMode,
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

describe('loadThemeMode', () => {
  it('无存储值时返回默认 modern', () => {
    expect(loadThemeMode()).toBe('modern')
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

  it('非法值回退 modern', () => {
    localStorage.setItem('cndb_theme', 'not-a-theme')
    expect(loadThemeMode()).toBe('modern')
  })

  it('localStorage 抛异常时回退 modern', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadThemeMode()).toBe('modern')
  })
})

describe('saveThemeMode / getThemeConfig', () => {
  it('saveThemeMode 写入 localStorage', () => {
    saveThemeMode('forest')
    expect(localStorage.getItem('cndb_theme')).toBe('forest')
  })

  it('getThemeConfig 返回对应主题配置', () => {
    expect(getThemeConfig('modern')).toBe(THEMES.modern)
    expect(getThemeConfig('oled')).toBe(THEMES.oled)
  })
})

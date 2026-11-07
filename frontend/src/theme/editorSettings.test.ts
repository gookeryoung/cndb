/** 编辑器外观设置读写测试（个人设置 → 编辑器）. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_EDITOR_SETTINGS,
  EDITOR_FONT_FAMILIES,
  EDITOR_FONT_META,
  EDITOR_FONT_SIZES,
  loadEditorSettings,
  saveEditorSettings,
} from './editorSettings'
import { EDITOR_THEME_IDS } from './editorThemes'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('编辑器设置常量', () => {
  it('默认值与常量表自洽', () => {
    expect(EDITOR_THEME_IDS).toContain(DEFAULT_EDITOR_SETTINGS.theme)
    expect(EDITOR_FONT_FAMILIES).toContain(DEFAULT_EDITOR_SETTINGS.font.family)
    expect(EDITOR_FONT_SIZES).toContain(DEFAULT_EDITOR_SETTINGS.font.size)
    expect(DEFAULT_EDITOR_SETTINGS).toEqual({
      theme: 'auto',
      font: { family: 'jetbrains', size: 'auto' },
    })
  })
})

describe('编辑器字体清单', () => {
  it('仅提供 JetBrains Mono / Cascadia Code / Maple Mono / 系统等宽', () => {
    expect(EDITOR_FONT_FAMILIES).toEqual([
      'jetbrains', 'cascadia-code', 'maple-mono', 'system',
    ])
    for (const id of EDITOR_FONT_FAMILIES) {
      expect(EDITOR_FONT_META[id].label.length).toBeGreaterThan(0)
      expect(EDITOR_FONT_META[id].css.length).toBeGreaterThan(0)
    }
    expect(EDITOR_FONT_META['cascadia-code'].css).toContain("'Cascadia Code'")
    expect(EDITOR_FONT_META['maple-mono'].css).toContain("'Maple Mono'")
  })
})

describe('loadEditorSettings', () => {
  it('无存储值时返回默认设置', () => {
    expect(loadEditorSettings()).toEqual(DEFAULT_EDITOR_SETTINGS)
  })

  it('合法持久化值原样返回', () => {
    localStorage.setItem(
      'cndb_editor_settings',
      JSON.stringify({ theme: 'one-dark', font: { family: 'system', size: 15 } }),
    )
    expect(loadEditorSettings()).toEqual({
      theme: 'one-dark',
      font: { family: 'system', size: 15 },
    })
    // 新增字体同样可持久化回读
    localStorage.setItem(
      'cndb_editor_settings',
      JSON.stringify({ theme: 'auto', font: { family: 'maple-mono', size: 'auto' } }),
    )
    expect(loadEditorSettings().font.family).toBe('maple-mono')
  })

  it('非法主题 / 字体 / 字号逐项回退默认', () => {
    localStorage.setItem(
      'cndb_editor_settings',
      JSON.stringify({ theme: 'nope', font: { family: 'comic', size: 99 } }),
    )
    expect(loadEditorSettings()).toEqual(DEFAULT_EDITOR_SETTINGS)
  })

  it('缺少 font 字段时回退默认字体设置', () => {
    localStorage.setItem('cndb_editor_settings', JSON.stringify({ theme: 'solarized-dark' }))
    expect(loadEditorSettings()).toEqual({
      theme: 'solarized-dark',
      font: DEFAULT_EDITOR_SETTINGS.font,
    })
  })

  it('JSON 损坏 / 存储异常时回退默认', () => {
    localStorage.setItem('cndb_editor_settings', '{broken')
    expect(loadEditorSettings()).toEqual(DEFAULT_EDITOR_SETTINGS)

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadEditorSettings()).toEqual(DEFAULT_EDITOR_SETTINGS)
  })
})

describe('saveEditorSettings', () => {
  it('写入后可往返读取', () => {
    const settings = {
      theme: 'high-contrast' as const,
      font: { family: 'maple-mono' as const, size: 13 as const },
    }
    saveEditorSettings(settings)
    expect(JSON.parse(localStorage.getItem('cndb_editor_settings') ?? '{}')).toEqual(settings)
    expect(loadEditorSettings()).toEqual(settings)
  })
})

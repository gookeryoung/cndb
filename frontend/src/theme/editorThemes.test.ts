/** 编辑器主题色板与外观扩展测试. */

import { describe, expect, it } from 'vitest'
import {
  EDITOR_THEME_IDS,
  EDITOR_THEME_META,
  editorAppearanceExtensions,
  getEditorPalette,
  resolveEditorTheme,
} from './editorThemes'
import { DEFAULT_EDITOR_SETTINGS } from './editorSettings'

describe('EDITOR_THEME_IDS / EDITOR_THEME_META', () => {
  it('元信息全量覆盖且 auto 排首位', () => {
    expect(EDITOR_THEME_IDS[0]).toBe('auto')
    expect(new Set(EDITOR_THEME_IDS).size).toBe(EDITOR_THEME_IDS.length)
    for (const id of EDITOR_THEME_IDS) {
      const meta = EDITOR_THEME_META[id]
      expect(meta.id).toBe(id)
      expect(meta.label.length).toBeGreaterThan(0)
      expect(meta.description.length).toBeGreaterThan(0)
    }
  })

  it('提供浅色与深色各至少两套（覆盖不同使用环境）', () => {
    const themes = EDITOR_THEME_IDS.filter(id => id !== 'auto').map(id => EDITOR_THEME_META[id])
    expect(themes.filter(t => t.isDark).length).toBeGreaterThanOrEqual(2)
    expect(themes.filter(t => !t.isDark).length).toBeGreaterThanOrEqual(2)
  })
})

describe('resolveEditorTheme / getEditorPalette', () => {
  it('auto 按应用主题明暗落到 GitHub 同族', () => {
    expect(resolveEditorTheme('auto', false)).toBe('github-light')
    expect(resolveEditorTheme('auto', true)).toBe('github-dark')
  })

  it('显式主题不受应用明暗影响', () => {
    expect(resolveEditorTheme('one-dark', false)).toBe('one-dark')
    expect(resolveEditorTheme('solarized-light', true)).toBe('solarized-light')
  })

  it('色板 ID 与解析结果一致，且背景 / 正文色互不相同', () => {
    const backgrounds = new Set<string>()
    for (const id of EDITOR_THEME_IDS) {
      const palette = getEditorPalette(id, false)
      expect(palette.id).toBe(resolveEditorTheme(id, false))
      expect(palette.bg).not.toBe(palette.text)
      backgrounds.add(`${palette.bg}|${getEditorPalette(id, true).bg}`)
    }
    // auto（随应用明暗）、github-light、github-dark、one-dark、solarized-light、
    // solarized-dark、high-contrast 各自成组
    expect(backgrounds.size).toBe(7)
  })

  it('非法持久化 ID 回退跟随应用，不抛错', () => {
    expect(getEditorPalette('nope' as never, true).id).toBe('github-dark')
  })
})

describe('editorAppearanceExtensions', () => {
  it('返回主题与语法高亮两个扩展', () => {
    const ext = editorAppearanceExtensions('github-light', false, DEFAULT_EDITOR_SETTINGS.font)
    expect(ext).toHaveLength(2)
  })

  it('配色 / 字体 / 字号任一变化都会得到不同的扩展实例（缓存按组合生效）', () => {
    const base = editorAppearanceExtensions('one-dark', true, DEFAULT_EDITOR_SETTINGS.font)
    expect(editorAppearanceExtensions('one-dark', true, DEFAULT_EDITOR_SETTINGS.font)[0]).toBe(base[0])
    expect(
      editorAppearanceExtensions('one-dark', true, { family: 'system', size: 16 })[0],
    ).not.toBe(base[0])
  })
})

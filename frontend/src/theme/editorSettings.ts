/** 编辑器外观设置：配色主题 / 等宽字体 / 字号（个人设置 → 编辑器）.
 *
 * 与全站字体设置（`fonts.ts`）分开：编辑器需要独立的等宽字体与字号，
 * 否则中文正文字号变化会把代码排版一起带跑。
 * 持久化到 localStorage，读写模式与 `fonts.ts` 保持一致。
 */

import { EDITOR_THEME_IDS, type EditorThemeId } from './editorThemes'

/* ─────────────── 字体 ─────────────── */

export const EDITOR_FONT_FAMILIES = ['jetbrains', 'system', 'inter'] as const
export type EditorFontFamily = (typeof EDITOR_FONT_FAMILIES)[number]

export interface EditorFontFamilyMeta {
  id: EditorFontFamily
  label: string
  description: string
  /** 直接写进 CodeMirror 主题的 font-family 值 */
  css: string
}

export const EDITOR_FONT_META: Record<EditorFontFamily, EditorFontFamilyMeta> = {
  jetbrains: {
    id: 'jetbrains',
    label: 'JetBrains Mono',
    description: '带连字的编程字体，代码最清晰',
    css: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  },
  system: {
    id: 'system',
    label: '系统等宽',
    description: '使用操作系统的默认等宽字体',
    css: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  },
  inter: {
    id: 'inter',
    label: 'Inter',
    description: '非等宽字体，接近正文观感',
    css: "'Inter', system-ui, sans-serif",
  },
}

export const EDITOR_FONT_SIZES = ['auto', 12, 13, 14, 15, 16] as const
export type EditorFontSize = (typeof EDITOR_FONT_SIZES)[number]

/** 字号选项文案：auto 跟随全站字号（body 当前基准） */
export const EDITOR_FONT_SIZE_LABEL: Record<EditorFontSize, string> = {
  auto: '跟随全站',
  12: '12 px',
  13: '13 px',
  14: '14 px',
  15: '15 px',
  16: '16 px',
}

export interface EditorFontSettings {
  family: EditorFontFamily
  size: EditorFontSize
}

export interface EditorSettings {
  /** 配色主题（auto = 跟随全站明暗） */
  theme: EditorThemeId
  font: EditorFontSettings
}

/** 局部更新载荷：font 可只给一个字段 */
export type EditorSettingsPatch = Partial<Omit<EditorSettings, 'font'>> & {
  font?: Partial<EditorFontSettings>
}

export const DEFAULT_EDITOR_SETTINGS: EditorSettings = {
  theme: 'auto',
  font: { family: 'jetbrains', size: 'auto' },
}

const EDITOR_KEY = 'cndb_editor_settings'

function isFontSize(value: unknown): value is EditorFontSize {
  return (EDITOR_FONT_SIZES as readonly unknown[]).includes(value)
}

export function loadEditorSettings(): EditorSettings {
  try {
    const raw = localStorage.getItem(EDITOR_KEY)
    if (!raw) return { ...DEFAULT_EDITOR_SETTINGS, font: { ...DEFAULT_EDITOR_SETTINGS.font } }
    const parsed = JSON.parse(raw) as Partial<EditorSettings> & {
      font?: Partial<EditorFontSettings>
    }
    const theme = EDITOR_THEME_IDS.includes(parsed.theme as EditorThemeId)
      ? (parsed.theme as EditorThemeId)
      : DEFAULT_EDITOR_SETTINGS.theme
    const family = EDITOR_FONT_FAMILIES.includes(parsed.font?.family as EditorFontFamily)
      ? (parsed.font!.family as EditorFontFamily)
      : DEFAULT_EDITOR_SETTINGS.font.family
    const size = isFontSize(parsed.font?.size)
      ? parsed.font!.size!
      : DEFAULT_EDITOR_SETTINGS.font.size
    return { theme, font: { family, size } }
  } catch { /* noop */ }
  return { ...DEFAULT_EDITOR_SETTINGS, font: { ...DEFAULT_EDITOR_SETTINGS.font } }
}

export function saveEditorSettings(settings: EditorSettings) {
  try { localStorage.setItem(EDITOR_KEY, JSON.stringify(settings)) } catch { /* noop */ }
}

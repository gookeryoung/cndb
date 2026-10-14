/** 主题配置聚合入口 — 10 种风格：
 * 浅色：modern / github-light / minimal / ocean / forest / sepia / sakura
 * 深色：github-dark / midnight / oled
 *
 * 具体 ThemeConfig 在 presets/{light,dark}.ts，元信息在 meta.ts，字体设置在 fonts.ts；
 * 本模块保留全部历史导出（含 loader / getThemeConfig），使既有导入路径不变。
 */

import type { ThemeConfig } from 'antd'

import { THEME_MODES } from './meta'
import type { ThemeMode } from './meta'
import {
  modernTheme,
  githubLightTheme,
  minimalTheme,
  oceanTheme,
  forestTheme,
  sepiaTheme,
  sakuraTheme,
} from './presets/light'
import {
  githubDarkTheme,
  midnightTheme,
  oledTheme,
} from './presets/dark'

export { THEME_META, THEME_MODES } from './meta'
export type { ThemeMeta, ThemeMode } from './meta'
export {
  DEFAULT_FONT_SETTINGS,
  FONT_SCALE_META,
  FONT_SCALES,
  loadFontSettings,
  saveFontSettings,
} from './fonts'
export type { FontScale, FontScaleMeta, FontSettings } from './fonts'

/* ─────────────── Ant Design ThemeConfig ─────────────── */

export const THEMES: Record<ThemeMode, ThemeConfig> = {
  modern: modernTheme,
  'github-dark': githubDarkTheme,
  'github-light': githubLightTheme,
  minimal: minimalTheme,
  ocean: oceanTheme,
  forest: forestTheme,
  sepia: sepiaTheme,
  sakura: sakuraTheme,
  midnight: midnightTheme,
  oled: oledTheme,
}

/* ─────────────── 持久化 helpers ─────────────── */

/** 默认主题 — loadThemeMode 兜底与主题页「恢复默认」共用单一来源 */
export const DEFAULT_THEME_MODE: ThemeMode = 'modern'

const THEME_KEY = 'cndb_theme'

/** 兼容老版本的 'light' / 'dark' 值 */
const LEGACY_MAP: Record<string, ThemeMode> = {
  light: 'modern',
  dark: 'github-dark',
}

export function loadThemeMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (!raw) return DEFAULT_THEME_MODE
    if (raw in LEGACY_MAP) return LEGACY_MAP[raw]
    if ((THEME_MODES as readonly string[]).includes(raw)) return raw as ThemeMode
  } catch { /* noop */ }
  return DEFAULT_THEME_MODE
}

export function saveThemeMode(mode: ThemeMode) {
  try { localStorage.setItem(THEME_KEY, mode) } catch { /* noop */ }
}

/** 各主题 Segmented 激活滑块（主题色底）上的可读前景色 — 亮度较高的主题色用深字保证对比 */
const SEGMENTED_ON_PRIMARY: Record<ThemeMode, string> = {
  modern: '#ffffff',
  'github-dark': '#0d1117',
  'github-light': '#ffffff',
  minimal: '#ffffff',
  ocean: '#ffffff',
  forest: '#ffffff',
  sepia: '#ffffff',
  sakura: '#ffffff',
  midnight: '#1d1830',
  oled: '#0a0a0a',
}

export function getThemeConfig(mode: ThemeMode): ThemeConfig {
  const config = THEMES[mode]
  return {
    ...config,
    components: {
      ...config.components,
      // Segmented 激活滑块填充主题色 + 反色文字，强化激活项与未激活项的对比
      Segmented: {
        itemSelectedBg: config.token?.colorPrimary ?? '#1677ff',
        itemSelectedColor: SEGMENTED_ON_PRIMARY[mode],
      },
    },
  }
}

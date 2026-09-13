/** 主题配置 — 4 种风格：modern / github-dark / github-light / minimal. */

import type { ThemeConfig } from 'antd'

/* ─────────────── Switch 组件统一 token ─────────────── */
const switchTokens = {
  trackHeight: 24,
  trackMinWidth: 48,
  trackHeightSM: 18,
  trackMinWidthSM: 36,
  handleSize: 20,
  handleSizeSM: 14,
}

/* ─────────────── 主题 ID / 元信息 ─────────────── */

export const THEME_MODES = ['modern', 'github-dark', 'github-light', 'minimal'] as const
export type ThemeMode = (typeof THEME_MODES)[number]

export interface ThemeMeta {
  id: ThemeMode
  label: string
  description: string
  isDark: boolean
  /** 主题在 body 上挂的 data 属性值，方便 CSS 变量覆盖 */
  bodyClass: string
}

export const THEME_META: Record<ThemeMode, ThemeMeta> = {
  modern: {
    id: 'modern',
    label: '现代',
    description: '明亮蓝紫调，默认推荐',
    isDark: false,
    bodyClass: 'theme-modern',
  },
  'github-dark': {
    id: 'github-dark',
    label: 'GitHub 深色',
    description: 'GitHub 风格的高对比度深色',
    isDark: true,
    bodyClass: 'theme-github-dark',
  },
  'github-light': {
    id: 'github-light',
    label: 'GitHub 浅色',
    description: 'GitHub 风格的浅色模式',
    isDark: false,
    bodyClass: 'theme-github-light',
  },
  minimal: {
    id: 'minimal',
    label: '极简',
    description: '中性灰，无装饰，低饱和度',
    isDark: false,
    bodyClass: 'theme-minimal',
  },
}

/* ─────────────── Ant Design ThemeConfig ─────────────── */

const commonFont =
  "system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif"

/** 现代（默认浅色） */
const modernTheme: ThemeConfig = {
  token: {
    colorPrimary: '#3b82f6',
    borderRadius: 6,
    colorBgBase: '#ffffff',
    colorTextBase: '#1f2937',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#f5f7fa',
      headerHeight: 52,
    },
  },
}

/** GitHub Dark — 颜色完全对齐 Primer 深色主题 */
const githubDarkTheme: ThemeConfig = {
  token: {
    colorPrimary: '#58a6ff',
    borderRadius: 6,
    colorBgBase: '#0d1117',
    colorTextBase: '#e6edf3',
    colorBgContainer: '#161b22',
    colorBgElevated: '#21262d',
    colorBorder: '#30363d',
    colorBorderSecondary: '#21262d',
    colorSplit: '#21262d',
    colorTextSecondary: '#8b949e',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#21262d',
      defaultColor: '#e6edf3',
      defaultBorderColor: '#30363d',
      defaultHoverBg: '#30363d',
    },
    Card: {
      colorBorderSecondary: '#30363d',
    },
    Table: {
      headerBg: '#0d1117',
      headerColor: '#8b949e',
      headerSortActiveBg: '#0d1117',
      headerSortHoverBg: '#161b22',
      rowHoverBg: '#161b22',
      rowSelectedBg: '#1f2937',
      borderColor: '#30363d',
      headerBorderRadius: 0,
    },
    Modal: {
      contentBg: '#161b22',
      headerBg: '#161b22',
    },
    Input: {
      colorBgContainer: '#0d1117',
      activeBorderColor: '#58a6ff',
      hoverBorderColor: '#30363d',
    },
    Select: {
      colorBgContainer: '#0d1117',
      optionSelectedBg: '#1f2937',
    },
    Layout: {
      headerBg: '#0d1117',
      siderBg: '#0d1117',
      bodyBg: '#010409',
      headerHeight: 52,
    },
  },
}

/** GitHub Light */
const githubLightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0969da',
    borderRadius: 6,
    colorBgBase: '#ffffff',
    colorTextBase: '#1f2328',
    colorBgContainer: '#f6f8fa',
    colorBgElevated: '#ffffff',
    colorBorder: '#d0d7de',
    colorBorderSecondary: '#d0d7de',
    colorSplit: '#d0d7de',
    colorTextSecondary: '#59636e',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f6f8fa',
      defaultColor: '#1f2328',
      defaultBorderColor: '#d0d7de',
      defaultHoverBg: '#d0d7de',
    },
    Table: {
      headerBg: '#f6f8fa',
      headerColor: '#59636e',
      rowHoverBg: '#f6f8fa',
      rowSelectedBg: '#ddf4ff',
      borderColor: '#d0d7de',
      headerBorderRadius: 0,
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#f6f8fa',
      bodyBg: '#ffffff',
      headerHeight: 52,
    },
  },
}

/** 极简 — 中性灰、无装饰 */
const minimalTheme: ThemeConfig = {
  token: {
    colorPrimary: '#525252',
    borderRadius: 2,
    colorBgBase: '#fafafa',
    colorTextBase: '#262626',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#d4d4d4',
    colorBorderSecondary: '#e5e5e5',
    colorSplit: '#e5e5e5',
    colorTextSecondary: '#737373',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#ffffff',
      defaultColor: '#262626',
      defaultBorderColor: '#d4d4d4',
      defaultHoverBg: '#f5f5f5',
    },
    Table: {
      headerBg: '#fafafa',
      headerColor: '#737373',
      rowHoverBg: '#f5f5f5',
      rowSelectedBg: '#f0f0f0',
      borderColor: '#e5e5e5',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e5e5e5',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#fafafa',
      headerHeight: 52,
    },
  },
}

export const THEMES: Record<ThemeMode, ThemeConfig> = {
  modern: modernTheme,
  'github-dark': githubDarkTheme,
  'github-light': githubLightTheme,
  minimal: minimalTheme,
}

/* ─────────────── 持久化 helpers ─────────────── */

const THEME_KEY = 'cndb_theme'

/** 兼容老版本的 'light' / 'dark' 值 */
const LEGACY_MAP: Record<string, ThemeMode> = {
  light: 'modern',
  dark: 'github-dark',
}

export function loadThemeMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (!raw) return 'modern'
    if (raw in LEGACY_MAP) return LEGACY_MAP[raw]
    if ((THEME_MODES as readonly string[]).includes(raw)) return raw as ThemeMode
  } catch { /* noop */ }
  return 'modern'
}

export function saveThemeMode(mode: ThemeMode) {
  try { localStorage.setItem(THEME_KEY, mode) } catch { /* noop */ }
}

export function getThemeConfig(mode: ThemeMode): ThemeConfig {
  return THEMES[mode]
}

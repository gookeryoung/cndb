/** 主题配置 — 10 种风格：
 * 浅色：modern / github-light / minimal / ocean / forest / sepia / sakura
 * 深色：github-dark / midnight / oled
 */

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

export const THEME_MODES = [
  'modern',
  'github-dark',
  'github-light',
  'minimal',
  'ocean',
  'forest',
  'sepia',
  'sakura',
  'midnight',
  'oled',
] as const
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
    label: '深色',
    description: '深色高对比度模式',
    isDark: true,
    bodyClass: 'theme-github-dark',
  },
  'github-light': {
    id: 'github-light',
    label: '浅色',
    description: '浅色明亮模式',
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
  ocean: {
    id: 'ocean',
    label: '海洋',
    description: '青蓝清爽，冷静专注',
    isDark: false,
    bodyClass: 'theme-ocean',
  },
  forest: {
    id: 'forest',
    label: '森野',
    description: '翠绿自然，舒缓放松',
    isDark: false,
    bodyClass: 'theme-forest',
  },
  sepia: {
    id: 'sepia',
    label: '纸感',
    description: '米黄纸调，温润护眼',
    isDark: false,
    bodyClass: 'theme-sepia',
  },
  sakura: {
    id: 'sakura',
    label: '樱粉',
    description: '柔和粉色，轻盈亲和',
    isDark: false,
    bodyClass: 'theme-sakura',
  },
  midnight: {
    id: 'midnight',
    label: '午夜紫',
    description: '深紫夜色，沉浸低扰',
    isDark: true,
    bodyClass: 'theme-midnight',
  },
  oled: {
    id: 'oled',
    label: '极夜黑',
    description: '纯黑高对比，OLED 省电',
    isDark: true,
    bodyClass: 'theme-oled',
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
      rowBg: '#fafafa',
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

/** 海洋 — 青蓝清爽浅色系 */
const oceanTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0891b2',
    borderRadius: 8,
    colorBgBase: '#ffffff',
    colorTextBase: '#0f3a45',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#cfe2e8',
    colorBorderSecondary: '#e3eef2',
    colorSplit: '#e3eef2',
    colorTextSecondary: '#5b7c88',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f0f8fa',
      defaultColor: '#0f3a45',
      defaultBorderColor: '#cfe2e8',
      defaultHoverBg: '#e0f0f5',
    },
    Table: {
      headerBg: '#eef7f9',
      headerColor: '#5b7c88',
      rowBg: '#f4fafb',
      rowHoverBg: '#f0f8fa',
      rowSelectedBg: '#d5f0f6',
      borderColor: '#dcebf0',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e3eef2',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#eef7f9',
      bodyBg: '#f0f8fa',
      headerHeight: 52,
    },
  },
}

/** 森野 — 翠绿自然浅色系 */
const forestTheme: ThemeConfig = {
  token: {
    colorPrimary: '#16a34a',
    borderRadius: 8,
    colorBgBase: '#ffffff',
    colorTextBase: '#14301b',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#d3e4d5',
    colorBorderSecondary: '#e7f0e8',
    colorSplit: '#e7f0e8',
    colorTextSecondary: '#5c7560',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f3f8f4',
      defaultColor: '#14301b',
      defaultBorderColor: '#d3e4d5',
      defaultHoverBg: '#e6f2e9',
    },
    Table: {
      headerBg: '#eef6ef',
      headerColor: '#5c7560',
      rowBg: '#f6faf7',
      rowHoverBg: '#f3f8f4',
      rowSelectedBg: '#d8f0de',
      borderColor: '#e0ece2',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e7f0e8',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#eef6ef',
      bodyBg: '#f2f7f3',
      headerHeight: 52,
    },
  },
}

/** 纸感 — 米黄纸调，温润护眼 */
const sepiaTheme: ThemeConfig = {
  token: {
    colorPrimary: '#a16207',
    borderRadius: 4,
    colorBgBase: '#fbf6ea',
    colorTextBase: '#43341f',
    colorBgContainer: '#fbf6ea',
    colorBgElevated: '#fffdf7',
    colorBorder: '#ddcfae',
    colorBorderSecondary: '#e8dec6',
    colorSplit: '#e8dec6',
    colorTextSecondary: '#7a6a4d',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f3ecd9',
      defaultColor: '#43341f',
      defaultBorderColor: '#ddcfae',
      defaultHoverBg: '#ebe0c6',
    },
    Table: {
      headerBg: '#f3ecd9',
      headerColor: '#7a6a4d',
      rowHoverBg: '#f6f0e0',
      rowSelectedBg: '#efe4c8',
      borderColor: '#e3d8bd',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e8dec6',
    },
    Input: {
      colorBgContainer: '#fffdf7',
    },
    Select: {
      colorBgContainer: '#fffdf7',
    },
    Layout: {
      headerBg: '#fbf6ea',
      siderBg: '#f3ecd9',
      bodyBg: '#efe7d2',
      headerHeight: 52,
    },
  },
}

/** 樱粉 — 柔和粉色，轻盈亲和 */
const sakuraTheme: ThemeConfig = {
  token: {
    colorPrimary: '#db2777',
    borderRadius: 10,
    colorBgBase: '#ffffff',
    colorTextBase: '#3d2230',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#f2d9e5',
    colorBorderSecondary: '#f8e7ef',
    colorSplit: '#f8e7ef',
    colorTextSecondary: '#92708a',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#fdf3f8',
      defaultColor: '#3d2230',
      defaultBorderColor: '#f2d9e5',
      defaultHoverBg: '#fae7f1',
    },
    Table: {
      headerBg: '#fceff6',
      headerColor: '#92708a',
      rowBg: '#fef8fb',
      rowHoverBg: '#fdf3f8',
      rowSelectedBg: '#f8dceb',
      borderColor: '#f5e0eb',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#f8e7ef',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fceff6',
      bodyBg: '#fdf5f9',
      headerHeight: 52,
    },
  },
}

/** 午夜紫 — 深紫夜色，沉浸低扰 */
const midnightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#a78bfa',
    borderRadius: 8,
    colorBgBase: '#15121f',
    colorTextBase: '#e9e4f5',
    colorBgContainer: '#1d1830',
    colorBgElevated: '#26203a',
    colorBorder: '#383150',
    colorBorderSecondary: '#2a2440',
    colorSplit: '#2a2440',
    colorTextSecondary: '#a299c2',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#26203a',
      defaultColor: '#e9e4f5',
      defaultBorderColor: '#383150',
      defaultHoverBg: '#332b52',
    },
    Card: {
      colorBorderSecondary: '#383150',
    },
    Table: {
      headerBg: '#15121f',
      headerColor: '#a299c2',
      headerSortActiveBg: '#15121f',
      headerSortHoverBg: '#1d1830',
      rowHoverBg: '#1d1830',
      rowSelectedBg: '#332a55',
      borderColor: '#383150',
      headerBorderRadius: 0,
    },
    Modal: {
      contentBg: '#1d1830',
      headerBg: '#1d1830',
    },
    Input: {
      colorBgContainer: '#15121f',
      activeBorderColor: '#a78bfa',
      hoverBorderColor: '#383150',
    },
    Select: {
      colorBgContainer: '#15121f',
      optionSelectedBg: '#332a55',
    },
    Layout: {
      headerBg: '#15121f',
      siderBg: '#15121f',
      bodyBg: '#100d1a',
      headerHeight: 52,
    },
  },
}

/** 极夜黑 — 纯黑高对比，AMOLED 友好 */
const oledTheme: ThemeConfig = {
  token: {
    colorPrimary: '#22d3ee',
    borderRadius: 4,
    colorBgBase: '#000000',
    colorTextBase: '#f5f5f5',
    colorBgContainer: '#0a0a0a',
    colorBgElevated: '#161616',
    colorBorder: '#262626',
    colorBorderSecondary: '#1a1a1a',
    colorSplit: '#1a1a1a',
    colorTextSecondary: '#a3a3a3',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#161616',
      defaultColor: '#f5f5f5',
      defaultBorderColor: '#2a2a2a',
      defaultHoverBg: '#262626',
    },
    Card: {
      colorBorderSecondary: '#262626',
    },
    Table: {
      headerBg: '#000000',
      headerColor: '#a3a3a3',
      headerSortActiveBg: '#000000',
      headerSortHoverBg: '#0a0a0a',
      rowHoverBg: '#141414',
      rowSelectedBg: '#1f1f1f',
      borderColor: '#262626',
      headerBorderRadius: 0,
    },
    Modal: {
      contentBg: '#0a0a0a',
      headerBg: '#0a0a0a',
    },
    Input: {
      colorBgContainer: '#000000',
      activeBorderColor: '#22d3ee',
      hoverBorderColor: '#262626',
    },
    Select: {
      colorBgContainer: '#000000',
      optionSelectedBg: '#1f1f1f',
    },
    Layout: {
      headerBg: '#000000',
      siderBg: '#000000',
      bodyBg: '#000000',
      headerHeight: 52,
    },
  },
}

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

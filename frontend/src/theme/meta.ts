/** 主题 ID 与元信息（标签、描述、明暗标记、body class）.
 *
 * 与 presets/ 中的具体 ThemeConfig 解耦：UI 只需元信息即可渲染主题选择器。
 */

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

/* ─────────────── 持久化偏好（需求 0066）：虚拟档 auto + 实际主题 ─────────────── */

/** 可持久化的主题偏好 = 「跟随系统」虚拟档 + 10 套实际主题.
 *
 * auto 不是一套主题：不进 THEME_META（无 bodyClass）、无 ThemeConfig，
 * 由 ThemeProvider 按 prefers-color-scheme 实时解析为 AUTO_LIGHT / AUTO_DARK。
 */
export const THEME_PREFERENCES = ['auto', ...THEME_MODES] as const
export type ThemePreference = ThemeMode | 'auto'

/** auto 的浅色落点 — 与深色落点同族（github-*），避免两态观感割裂（0066 C4） */
export const AUTO_LIGHT: ThemeMode = 'github-light'
/** auto 的深色落点（0066 C4） */
export const AUTO_DARK: ThemeMode = 'github-dark'

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

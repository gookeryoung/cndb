import type { ThemeConfig } from 'antd'

/** Switch 组件 token — 确保 trackHeight : trackMinWidth ≈ 1:2 的协调比例 */
const switchTokens = {
  trackHeight: 24,
  trackMinWidth: 48,
  trackHeightSM: 18,
  trackMinWidthSM: 36,
  handleSize: 20,
  handleSizeSM: 14,
}

export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#3b82f6',
    borderRadius: 6,
    colorBgBase: '#ffffff',
    colorTextBase: '#1f2937',
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Switch: switchTokens,
  },
}

export const darkTheme: ThemeConfig = {
  token: {
    colorPrimary: '#60a5fa',
    borderRadius: 6,
    colorBgBase: '#0b1220',
    colorTextBase: '#e5e7eb',
  },
  components: {
    Switch: switchTokens,
  },
}

export type ThemeMode = 'light' | 'dark'
const THEME_KEY = 'cndb_theme'

export function loadThemeMode(): ThemeMode {
  try {
    const v = localStorage.getItem(THEME_KEY) as ThemeMode | null
    if (v === 'light' || v === 'dark') return v
  } catch { /* noop */ }
  return 'light'
}

export function saveThemeMode(mode: ThemeMode) {
  try { localStorage.setItem(THEME_KEY, mode) } catch { /* noop */ }
}

export function getThemeConfig(mode: ThemeMode): ThemeConfig {
  return mode === 'dark' ? darkTheme : lightTheme
}

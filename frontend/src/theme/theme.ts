import type { ThemeConfig } from 'antd'

export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#3b82f6',
    borderRadius: 6,
    colorBgBase: '#ffffff',
    colorTextBase: '#1f2937',
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif",
  },
}

export const darkTheme: ThemeConfig = {
  token: {
    colorPrimary: '#60a5fa',
    borderRadius: 6,
    colorBgBase: '#0b1220',
    colorTextBase: '#e5e7eb',
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

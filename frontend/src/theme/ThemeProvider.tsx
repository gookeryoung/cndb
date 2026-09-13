/** 主题切换 Provider — 维护多主题状态并注入 antd ConfigProvider. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { getThemeConfig, loadThemeMode, saveThemeMode, THEME_META, type ThemeMode } from '@/theme/theme'

interface ThemeContextValue {
  mode: ThemeMode
  setMode: (m: ThemeMode) => void
  /** 当前主题是否深色 — 方便组件内做针对性分支 */
  isDark: boolean
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

/** 清理所有可能的主题 class，只保留当前的 */
function applyBodyClass(mode: ThemeMode) {
  const allClasses = Object.values(THEME_META).map(t => t.bodyClass)
  const body = document.body
  allClasses.forEach(cls => body.classList.remove(cls))
  body.classList.add(THEME_META[mode].bodyClass)

  // 向后兼容：保留 theme-dark class 给老 CSS 规则
  body.classList.toggle('theme-dark', THEME_META[mode].isDark)
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => loadThemeMode())

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m)
    saveThemeMode(m)
  }, [])

  useEffect(() => {
    applyBodyClass(mode)
  }, [mode])

  const isDark = THEME_META[mode].isDark

  const value = useMemo<ThemeContextValue>(() => ({ mode, setMode, isDark }), [mode, setMode, isDark])

  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          ...getThemeConfig(mode),
          algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        }}
      >
        {children}
      </ConfigProvider>
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}

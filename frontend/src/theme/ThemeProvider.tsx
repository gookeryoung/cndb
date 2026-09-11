/** 主题切换 Provider — 维护 light/dark 状态并注入 antd ConfigProvider. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { getThemeConfig, loadThemeMode, saveThemeMode, type ThemeMode } from '@/theme/theme'

interface ThemeContextValue {
  mode: ThemeMode
  toggle: () => void
  setMode: (m: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => loadThemeMode())

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m)
    saveThemeMode(m)
  }, [])

  const toggle = useCallback(() => {
    setModeState(prev => {
      const next = prev === 'dark' ? 'light' : 'dark'
      saveThemeMode(next)
      return next
    })
  }, [])

  // 同步 body class 方便 CSS 变量覆盖
  useEffect(() => {
    document.body.classList.toggle('theme-dark', mode === 'dark')
  }, [mode])

  const value = useMemo<ThemeContextValue>(() => ({ mode, toggle, setMode }), [mode, toggle, setMode])

  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          ...getThemeConfig(mode),
          algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
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

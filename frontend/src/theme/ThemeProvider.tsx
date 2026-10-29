/** 主题切换 Provider — 维护多主题状态并注入 antd ConfigProvider. */

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { App as AntApp, ConfigProvider, theme as antdTheme } from 'antd'
import { StyleProvider, legacyLogicalPropertiesTransformer } from '@ant-design/cssinjs'
import zhCN from 'antd/locale/zh_CN'
import {
  getThemeConfig, themeCssVars, loadThemeMode, saveThemeMode,
  loadFontSettings, saveFontSettings,
  FONT_SCALE_META, THEME_META, AUTO_LIGHT, AUTO_DARK,
  type ThemeMode, type ThemePreference, type FontScale, type FontSettings,
} from '@/theme/theme'
import { applyThemeMixVars } from '@/theme/themeMix'
import { WEIGHT } from '@/theme/tokens'

interface ThemeContextValue {
  /** 当前生效的实际主题（pref=auto 时为系统解析结果） */
  mode: ThemeMode
  /** 持久化的主题偏好（auto / 具体主题）— 设置页与快捷菜单据此回显 */
  pref: ThemePreference
  setMode: (m: ThemePreference) => void
  /** 当前主题是否深色 — 方便组件内做针对性分支 */
  isDark: boolean
  /** 字体设置（字号档位 / 全局加粗） */
  font: FontSettings
  setFontScale: (s: FontScale) => void
  setFontBold: (b: boolean) => void
}

/** 系统当前是否偏好深色 — jsdom / 老内核无 matchMedia 时按浅色兜底. */
function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches
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

/** 把主题派生的圆角档位下发到 :root，index.css 里手写的卡片/浮层据此跟随主题 */
function applyThemeVars(mode: ThemeMode) {
  const root = document.documentElement
  for (const [name, value] of Object.entries(themeCssVars(mode))) {
    root.style.setProperty(name, value)
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // 持久化层：用户偏好（auto / 具体主题），localStorage 只存这一层（0066 C1）
  const [pref, setPrefState] = useState<ThemePreference>(() => {
    const m = loadThemeMode()
    // 首次进入时把默认值也持久化，保证 localStorage 始终有值
    try {
      const raw = localStorage.getItem('cndb_theme')
      if (!raw) saveThemeMode(m)
    } catch { /* noop */ }
    return m
  })

  // 系统层：pref=auto 时按系统明暗解析生效主题；change 事件实时跟随（0066 C3）
  const [systemDark, setSystemDark] = useState<boolean>(systemPrefersDark)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  const setMode = useCallback((m: ThemePreference) => {
    setPrefState(m)
    saveThemeMode(m)
  }, [])

  // 生效主题：auto 按系统解析（C4），具体偏好原样生效（C6）
  const mode: ThemeMode = pref === 'auto' ? (systemDark ? AUTO_DARK : AUTO_LIGHT) : pref

  const [font, setFontState] = useState<FontSettings>(loadFontSettings)

  const setFontScale = useCallback((s: FontScale) => {
    setFontState(prev => {
      const next = { ...prev, scale: s }
      saveFontSettings(next)
      return next
    })
  }, [])

  const setFontBold = useCallback((b: boolean) => {
    setFontState(prev => {
      const next = { ...prev, bold: b }
      saveFontSettings(next)
      return next
    })
  }, [])

  // 用 layout effect：Chrome 81 的首帧必须已挂好主题 class 与变量，避免闪一下默认主题
  useLayoutEffect(() => {
    applyBodyClass(mode)
    applyThemeVars(mode)
    // Chrome 81 没有 color-mix()：按刚挂好的主题变量重算 --cn-mix-* 兜底（现代内核直接跳过）
    applyThemeMixVars()
  }, [mode])

  // 字体设置：注入 body 基础字号与字重（antd 组件字号经 ConfigProvider token 下发）
  // 未开启加粗时显式写 400，避免 body 继承其他样式抬到 600
  useEffect(() => {
    document.body.style.fontSize = `${FONT_SCALE_META[font.scale].px}px`
    document.body.style.fontWeight = String(font.bold ? WEIGHT.semibold : WEIGHT.regular)
  }, [font])

  const isDark = THEME_META[mode].isDark

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, pref, setMode, isDark, font, setFontScale, setFontBold }),
    [mode, pref, setMode, isDark, font, setFontScale, setFontBold],
  )

  const baseConfig = getThemeConfig(mode)

  return (
    <ThemeContext.Provider value={value}>
      {/* Chrome 81 不支持 :where() / 逻辑属性 / inset：
          hashPriority="high" 去掉 :where() 包裹，transformer 把逻辑属性转物理属性（ADR 0026 D2） */}
      <StyleProvider
        hashPriority="high"
        transformers={[legacyLogicalPropertiesTransformer]}
      >
        <ConfigProvider
          locale={zhCN}
          theme={{
            ...baseConfig,
            algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
            // 字体设置覆盖主题 token 的字号/字重，其余 token（配色等）保持主题原值
            token: {
              ...baseConfig.token,
              fontSize: FONT_SCALE_META[font.scale].px,
              // 强调字重默认 600，开启全局加粗时抬升一档到 700
              fontWeightStrong: font.bold ? WEIGHT.bold : WEIGHT.semibold,
            },
          }}
        >
          <AntApp>{children}</AntApp>
        </ConfigProvider>
      </StyleProvider>
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}

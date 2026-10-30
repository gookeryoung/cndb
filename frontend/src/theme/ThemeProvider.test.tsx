/**
 * ThemeProvider 组件测试 —— 多主题状态与 antd 注入.
 *
 * 覆盖：默认主题 / 切换主题（body class + localStorage）/ isDark 派生 /
 * 首次进入持久化默认值 / useTheme 越界使用报错 / 字体设置（字号/加粗）应用与持久化。
 */

import { describe, expect, it, vi } from 'vitest'
import { screen, render, act } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { ThemeProvider, useTheme } from './ThemeProvider'

/** 主题探针 —— 展示当前 mode/isDark 并提供切换按钮 */
function ThemeProbe() {
  const { mode, setMode, isDark } = useTheme()
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="is-dark">{String(isDark)}</span>
      <button onClick={() => setMode('oled')}>切到 oled</button>
      <button onClick={() => setMode('sakura')}>切到 sakura</button>
    </div>
  )
}

/** 字体探针 —— 展示字体设置并提供变更按钮 */
function FontProbe() {
  const { font, setFontScale, setFontBold } = useTheme()
  return (
    <div>
      <span data-testid="font-scale">{font.scale}</span>
      <span data-testid="font-bold">{String(font.bold)}</span>
      <button onClick={() => setFontScale('large')}>切到 large</button>
      <button onClick={() => setFontBold(true)}>开加粗</button>
    </div>
  )
}

/** 可控 matchMedia 桩：返回值可变、change 监听可手动派发（0066 C3 用） */
function stubMatchMedia(initialDark: boolean) {
  const listeners = new Set<(e: { matches: boolean }) => void>()
  let dark = initialDark
  const mql = {
    get matches() { return dark },
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => listeners.add(cb),
    removeEventListener: (_: string, cb: (e: { matches: boolean }) => void) => listeners.delete(cb),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: () => mql,
  })
  return {
    setDark(next: boolean) {
      dark = next
      listeners.forEach(cb => cb({ matches: next }))
    },
  }
}

describe('ThemeProvider', () => {
  it('默认偏好 auto：按系统浅色解析为 github-light，localStorage 持久化 auto（C1/C4/C5）', () => {
    stubMatchMedia(false)
    localStorage.clear()
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('mode')).toHaveTextContent('github-light')
    expect(screen.getByTestId('is-dark')).toHaveTextContent('false')
    expect(document.body).toHaveClass('theme-github-light')
    expect(localStorage.getItem('cndb_theme')).toBe('auto')
  })

  it('auto + 系统深色：解析为 github-dark', () => {
    stubMatchMedia(true)
    localStorage.clear()
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('mode')).toHaveTextContent('github-dark')
    expect(screen.getByTestId('is-dark')).toHaveTextContent('true')
    expect(document.body).toHaveClass('theme-github-dark')
    expect(document.body).toHaveClass('theme-dark')
  })

  it('auto 下系统明暗实时切换：body class 跟随变化（C3）', () => {
    const media = stubMatchMedia(false)
    localStorage.clear()
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    expect(document.body).toHaveClass('theme-github-light')
    act(() => media.setDark(true))
    expect(screen.getByTestId('mode')).toHaveTextContent('github-dark')
    expect(document.body).toHaveClass('theme-github-dark')
    expect(document.body).not.toHaveClass('theme-github-light')
    act(() => media.setDark(false))
    expect(document.body).toHaveClass('theme-github-light')
  })

  it('显式选择具体主题后系统切换不再影响生效主题（C6）', () => {
    const media = stubMatchMedia(false)
    localStorage.clear()
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    fireEvent.click(screen.getByText('切到 sakura'))
    expect(document.body).toHaveClass('theme-sakura')

    // 系统切到深色：pref 为具体主题，不跟随
    act(() => media.setDark(true))
    expect(screen.getByTestId('mode')).toHaveTextContent('sakura')
    expect(document.body).toHaveClass('theme-sakura')
    expect(localStorage.getItem('cndb_theme')).toBe('sakura')
  })

  it('切换到深色主题：mode/isDark 更新，body class 切换并保留 theme-dark 兼容标记', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    fireEvent.click(screen.getByText('切到 oled'))

    expect(screen.getByTestId('mode')).toHaveTextContent('oled')
    expect(screen.getByTestId('is-dark')).toHaveTextContent('true')
    expect(document.body).toHaveClass('theme-oled')
    expect(document.body).toHaveClass('theme-dark')
    expect(localStorage.getItem('cndb_theme')).toBe('oled')
  })

  it('切换到浅色主题时移除 theme-dark 兼容标记，且旧主题 class 被清理', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    fireEvent.click(screen.getByText('切到 oled'))
    fireEvent.click(screen.getByText('切到 sakura'))

    expect(document.body).toHaveClass('theme-sakura')
    expect(document.body).not.toHaveClass('theme-oled')
    expect(document.body).not.toHaveClass('theme-dark')
    expect(localStorage.getItem('cndb_theme')).toBe('sakura')
  })

  it('localStorage 已有值时以其为初始主题', () => {
    localStorage.setItem('cndb_theme', 'sepia')
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('mode')).toHaveTextContent('sepia')
    expect(document.body).toHaveClass('theme-sepia')
  })

  it('useTheme 在 Provider 外使用时抛出明确错误', () => {
    // 屏蔽 React 渲染错误日志噪音
    const spy = vi.spyOn(console, 'error').mockImplementation(() => { })
    // React 18 createRoot 下渲染错误不再同步抛出，而是经 reportError 派发到 window error 事件
    const messages: string[] = []
    const onError = (e: ErrorEvent) => {
      e.preventDefault()
      messages.push(e.message)
    }
    window.addEventListener('error', onError)
    try {
      render(<ThemeProbe />)
    } catch (e) {
      // 兼容同步抛出路径
      messages.push((e as Error).message)
    } finally {
      window.removeEventListener('error', onError)
    }
    expect(messages.some(m => m.includes('useTheme must be used inside <ThemeProvider>'))).toBe(true)
    spy.mockRestore()
  })

  it('切换主题时 documentElement 短暂挂载 theme-switching 过渡类，首挂载不挂', () => {
    // 覆盖本文件前序测试的 matchMedia 桩：reduce 查询必须返回 false，否则误判跳过过渡
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
      }),
    })
    vi.useFakeTimers()
    try {
      render(
        <ThemeProvider>
          <ThemeProbe />
        </ThemeProvider>,
      )
      // 首次挂载直接落主题，不做过渡（避免首屏从默认色渐变）
      expect(document.documentElement).not.toHaveClass('theme-switching')

      fireEvent.click(screen.getByText('切到 oled'))
      expect(document.documentElement).toHaveClass('theme-switching')

      // 过渡窗口（200ms + 80ms 余量）结束后移除，不影响日常交互
      act(() => { vi.advanceTimersByTime(300) })
      expect(document.documentElement).not.toHaveClass('theme-switching')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('ThemeProvider 字体设置', () => {
  it('默认字体设置：standard / 不加粗，body 基础字号 14px 字重 400', () => {
    localStorage.clear()
    render(
      <ThemeProvider>
        <FontProbe />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('font-scale')).toHaveTextContent('standard')
    expect(screen.getByTestId('font-bold')).toHaveTextContent('false')
    expect(document.body.style.fontSize).toBe('14px')
    expect(document.body.style.fontWeight).toBe('400')
  })

  it('切换字号档位：body 字号同步更新并持久化到 localStorage', () => {
    localStorage.clear()
    render(
      <ThemeProvider>
        <FontProbe />
      </ThemeProvider>,
    )

    fireEvent.click(screen.getByText('切到 large'))

    expect(screen.getByTestId('font-scale')).toHaveTextContent('large')
    expect(document.body.style.fontSize).toBe('16px')
    const persisted = JSON.parse(localStorage.getItem('cndb_font') ?? '{}') as { scale?: string; bold?: boolean }
    expect(persisted.scale).toBe('large')
    expect(persisted.bold).toBe(false)
  })

  it('开启全局加粗：body 字重同步更新并持久化', () => {
    localStorage.clear()
    render(
      <ThemeProvider>
        <FontProbe />
      </ThemeProvider>,
    )

    fireEvent.click(screen.getByText('开加粗'))

    expect(screen.getByTestId('font-bold')).toHaveTextContent('true')
    expect(document.body.style.fontWeight).toBe('600')
    const persisted = JSON.parse(localStorage.getItem('cndb_font') ?? '{}') as { scale?: string; bold?: boolean }
    expect(persisted.bold).toBe(true)
  })

  it('localStorage 已有字体设置时以其为初始值', () => {
    localStorage.clear()
    localStorage.setItem('cndb_font', JSON.stringify({ scale: 'huge', bold: true }))
    render(
      <ThemeProvider>
        <FontProbe />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('font-scale')).toHaveTextContent('huge')
    expect(screen.getByTestId('font-bold')).toHaveTextContent('true')
    expect(document.body.style.fontSize).toBe('18px')
    expect(document.body.style.fontWeight).toBe('600')
  })
})

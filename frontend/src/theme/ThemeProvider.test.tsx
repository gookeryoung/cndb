/**
 * ThemeProvider 组件测试 —— 多主题状态与 antd 注入.
 *
 * 覆盖：默认主题 / 切换主题（body class + localStorage）/ isDark 派生 /
 * 首次进入持久化默认值 / useTheme 越界使用报错。
 */

import { describe, expect, it, vi } from 'vitest'
import { screen, render } from '@testing-library/react'
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

describe('ThemeProvider', () => {
  it('默认渲染 modern 主题，body 挂 theme-modern class，localStorage 持久化默认值', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('mode')).toHaveTextContent('modern')
    expect(screen.getByTestId('is-dark')).toHaveTextContent('false')
    expect(document.body).toHaveClass('theme-modern')
    expect(localStorage.getItem('cndb_theme')).toBe('modern')
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
    expect(() => render(<ThemeProbe />)).toThrow('useTheme must be used inside <ThemeProvider>')
    spy.mockRestore()
  })
})

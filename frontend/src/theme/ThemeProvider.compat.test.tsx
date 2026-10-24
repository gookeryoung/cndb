/**
 * ThemeProvider 的 Chromium 81 样式降级（ADR 0026 P0）。
 *
 * antd 5 默认用 :where() 包裹选择器，并把 paddingInline / inset 等逻辑属性写进运行时样式；
 * Chrome 81 前者整条丢弃、后者直接忽略。这里断言 StyleProvider 的降级真实生效。
 */

import { render, screen } from '@testing-library/react'
import { Button, Space } from 'antd'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider } from './ThemeProvider'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.removeAttribute('style')
  document.documentElement.removeAttribute('style')
})

function injectedCss(): string {
  return Array.from(document.querySelectorAll('style'))
    .map((node) => node.textContent ?? '')
    .join('\n')
}

function renderAntdSample() {
  render(
    <ThemeProvider>
      <Space>
        <Button type="primary">兼容按钮</Button>
      </Space>
    </ThemeProvider>,
  )
  expect(screen.getByText('兼容按钮')).toBeInTheDocument()
}

describe('ThemeProvider 的 Chromium 81 样式降级', () => {
  it('antd 注入的样式不含 :where()', () => {
    renderAntdSample()
    expect(injectedCss()).not.toContain(':where(')
  })

  it('逻辑属性被转换为物理属性', () => {
    renderAntdSample()
    const css = injectedCss()
    expect(css).toContain('padding-left')
    expect(css).not.toMatch(/padding-inline/)
    expect(css).not.toMatch(/margin-inline/)
  })

  it('旧内核首帧前写入 --cn-mix-* 兜底变量', () => {
    vi.stubGlobal('CSS', { supports: () => false })
    document.body.style.setProperty('--cn-brand-color', '#1677ff')
    document.body.style.setProperty('--cn-bg-container', '#ffffff')

    renderAntdSample()

    expect(document.documentElement.style.getPropertyValue('--cn-mix-brand-color-12-bg-container'))
      .toBe('rgb(227, 239, 255)')
  })
})

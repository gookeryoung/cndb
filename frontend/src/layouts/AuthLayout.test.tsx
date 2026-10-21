/**
 * AuthLayout 布局测试 —— 认证页容器渲染.
 *
 * 验证点：children 在 420px 居中容器内；动态背景懒加载后存在且 aria-hidden，
 * 右下角切换器在背景层外（ADR 0016 C4 / D8 / D10）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'

import AuthLayout from './AuthLayout'

describe('AuthLayout 布局', () => {
  beforeEach(() => {
    window.localStorage.clear()
    // jsdom 未实现 canvas 2D：返回 null 让引擎走 noop 降级，测试只关心 DOM 契约
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  })

  it('渲染 children 内容', async () => {
    renderProviders(
      <AuthLayout>
        <div>登录卡片探针</div>
      </AuthLayout>,
    )

    expect(await screen.findByText('登录卡片探针')).toBeInTheDocument()
  })

  it('children 位于 420px 宽的内容层', () => {
    const { container } = renderProviders(
      <AuthLayout>
        <div>内容</div>
      </AuthLayout>,
    )

    const body = container.querySelector('.auth-shell-body')
    expect(body).toHaveStyle({ width: '420px', maxWidth: '100%' })
  })

  it('懒加载动态背景层与切换器，画布 aria-hidden 且标注默认效果', async () => {
    const { container } = renderProviders(
      <AuthLayout>
        <div>内容</div>
      </AuthLayout>,
    )

    await waitFor(() => {
      expect(container.querySelector('.auth-bg-layer')).not.toBeNull()
    })
    const layer = container.querySelector('.auth-bg-layer')
    expect(layer).toHaveAttribute('aria-hidden', 'true')
    expect(layer).toHaveAttribute('data-effect', 'flowfield')
    expect(container.querySelector('canvas.auth-bg-canvas')).toBeInTheDocument()

    const switcher = container.querySelector('.auth-bg-switch')
    expect(switcher).toBeInTheDocument()
    expect(layer?.contains(switcher)).toBe(false)
  })
})

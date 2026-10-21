/**
 * AuthLayout 布局测试 —— 认证页容器渲染.
 *
 * 验证点：children 在 420px 居中容器内；动态背景懒加载后存在；
 * 右下角切换器改变变体并持久化到 localStorage（ADR 0014 C4 / C9 / D10）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AUTH_BACKGROUND_STORAGE_KEY } from '@/components/auth-background/preference'
import { renderProviders } from '@/test/render-providers'

import AuthLayout from './AuthLayout'

describe('AuthLayout 布局', () => {
  beforeEach(() => {
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

  it('懒加载背景层，默认星座且 aria-hidden', async () => {
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
    expect(layer).toHaveAttribute('data-variant', 'constellation')
    expect(container.querySelector('canvas.auth-bg-canvas')).toBeInTheDocument()
  })

  it('切换器改变背景变体并写入 localStorage', async () => {
    const user = userEvent.setup()
    const { container } = renderProviders(
      <AuthLayout>
        <div>内容</div>
      </AuthLayout>,
    )
    await waitFor(() => {
      expect(container.querySelector('.auth-bg-layer')).not.toBeNull()
    })

    await user.click(screen.getByTestId('auth-bg-switch'))

    expect(container.querySelector('.auth-bg-layer')).toHaveAttribute('data-variant', 'nebula')
    expect(localStorage.getItem(AUTH_BACKGROUND_STORAGE_KEY)).toBe('nebula')
    expect(screen.getByTestId('auth-bg-switch')).toHaveTextContent('星云')
  })

  it('读取已保存的变体作为初始背景', async () => {
    localStorage.setItem(AUTH_BACKGROUND_STORAGE_KEY, 'aurora')
    const { container } = renderProviders(
      <AuthLayout>
        <div>内容</div>
      </AuthLayout>,
    )

    await waitFor(() => {
      expect(container.querySelector('.auth-bg-layer')).toHaveAttribute('data-variant', 'aurora')
    })
  })
})

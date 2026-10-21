/**
 * 认证页背景组件测试（ADR 0016 §7 组件层）.
 *
 * 引擎被 mock：本文件只验证组件契约（画布 / 可访问性 / 效果切换 / 卸载清理），
 * 真实绘制与生命周期由 engine.test.ts 覆盖。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'

import AuthBackground from './AuthBackground'
import { AUTH_EFFECT_STORAGE_KEY } from './preference'

const { mountAuthBackground } = vi.hoisted(() => ({
  mountAuthBackground: vi.fn((_canvas: HTMLCanvasElement, _options: unknown) => vi.fn()),
}))

vi.mock('./engine', () => ({ mountAuthBackground }))

describe('AuthBackground', () => {
  beforeEach(() => {
    window.localStorage.clear()
    mountAuthBackground.mockClear()
  })

  it('默认渲染 aria-hidden 的流场动效画布与切换器', () => {
    const { container } = renderProviders(<AuthBackground />)

    const layer = container.querySelector('.auth-bg-layer')
    expect(layer).toHaveAttribute('aria-hidden', 'true')
    expect(layer).toHaveAttribute('data-effect', 'flowfield')
    expect(container.querySelector('canvas.auth-bg-canvas')).toBeInTheDocument()

    // 切换器必须在背景层外，否则会被 aria-hidden 吞掉
    const switcher = screen.getByTestId('auth-bg-switch')
    expect(switcher).toBeInTheDocument()
    expect(layer?.contains(switcher)).toBe(false)
  })

  it('挂载时把画布、效果与设备 / 动效选项交给引擎', () => {
    const { container } = renderProviders(<AuthBackground />)

    expect(mountAuthBackground).toHaveBeenCalledTimes(1)
    const [canvas, options] = mountAuthBackground.mock.calls[0]
    expect(canvas).toBe(container.querySelector('canvas.auth-bg-canvas'))
    expect(options).toMatchObject({ reducedMotion: false, effect: 'flowfield' })
  })

  it('已有星系偏好时直接以星系挂载', () => {
    window.localStorage.setItem(AUTH_EFFECT_STORAGE_KEY, 'galaxy')

    const { container } = renderProviders(<AuthBackground />)

    expect(container.querySelector('.auth-bg-layer')).toHaveAttribute('data-effect', 'galaxy')
    expect(mountAuthBackground.mock.calls[0][1]).toMatchObject({ effect: 'galaxy' })
  })

  it('点击切换器切到宇宙星系、重挂载引擎并写入偏好', () => {
    const { container } = renderProviders(<AuthBackground />)

    fireEvent.click(screen.getByTestId('auth-bg-switch'))

    expect(container.querySelector('.auth-bg-layer')).toHaveAttribute('data-effect', 'galaxy')
    expect(screen.getByTestId('auth-bg-switch')).toHaveTextContent('宇宙星系')
    expect(mountAuthBackground).toHaveBeenCalledTimes(2)
    expect(mountAuthBackground.mock.calls[1][1]).toMatchObject({ effect: 'galaxy' })
    expect(window.localStorage.getItem(AUTH_EFFECT_STORAGE_KEY)).toBe('galaxy')
  })

  it('卸载时调用引擎 dispose', () => {
    const { unmount } = renderProviders(<AuthBackground />)
    const dispose = mountAuthBackground.mock.results[0].value

    unmount()

    expect(dispose).toHaveBeenCalledTimes(1)
  })
})

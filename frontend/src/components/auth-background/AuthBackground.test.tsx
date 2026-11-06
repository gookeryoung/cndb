/**
 * 认证页背景组件测试（ADR 0016 §7 组件层）.
 *
 * 引擎被 mock：本文件只验证组件契约（画布 / 可访问性 / 设备档位 / 卸载清理），
 * 真实绘制与生命周期由 engine.test.ts 覆盖。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { renderProviders } from '@/test/render-providers'

import AuthBackground from './AuthBackground'

const { mountAuthBackground } = vi.hoisted(() => ({
  mountAuthBackground: vi.fn((_canvas: HTMLCanvasElement, _options: unknown) => vi.fn()),
}))

vi.mock('./engine', () => ({ mountAuthBackground }))

describe('AuthBackground', () => {
  beforeEach(() => {
    mountAuthBackground.mockClear()
  })

  it('渲染 aria-hidden 的静态晶格画布，且不再有切换器', () => {
    const { container } = renderProviders(<AuthBackground />)

    const layer = container.querySelector('.auth-bg-layer')
    expect(layer).toHaveAttribute('aria-hidden', 'true')
    expect(container.querySelector('canvas.auth-bg-canvas')).toBeInTheDocument()
    expect(container.querySelector('.auth-bg-switch')).toBeNull()
    expect(container.querySelector('[data-effect]')).toBeNull()
  })

  it('挂载时把画布与设备档位交给引擎', () => {
    const { container } = renderProviders(<AuthBackground />)

    expect(mountAuthBackground).toHaveBeenCalledTimes(1)
    const [canvas, options] = mountAuthBackground.mock.calls[0]
    expect(canvas).toBe(container.querySelector('canvas.auth-bg-canvas'))
    expect(options).toEqual({ isMobile: false })
  })

  it('卸载时调用引擎 dispose', () => {
    const { unmount } = renderProviders(<AuthBackground />)
    const dispose = mountAuthBackground.mock.results[0].value

    unmount()

    expect(dispose).toHaveBeenCalledTimes(1)
  })
})

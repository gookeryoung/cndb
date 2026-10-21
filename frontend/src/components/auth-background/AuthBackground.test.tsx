/**
 * 认证页背景组件测试（ADR 0014 §7 组件层）.
 *
 * 引擎被 mock：本文件只验证组件契约（画布 / 可访问性 / 主题重建 / 卸载清理），
 * 真实绘制与生命周期由 engine.test.ts 覆盖。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useTheme } from '@/theme/ThemeProvider'
import { renderProviders } from '@/test/render-providers'

import AuthBackground from './AuthBackground'

const { mountAuthBackground } = vi.hoisted(() => ({
  mountAuthBackground: vi.fn((_canvas: HTMLCanvasElement, _options: unknown) => vi.fn()),
}))

vi.mock('./engine', () => ({ mountAuthBackground }))

/** 主题切换探针：点击后切到深色主题，校验引擎以新模式重建 */
function ThemeSwitchProbe() {
  const { setMode } = useTheme()
  return (
    <button type="button" onClick={() => setMode('github-dark')}>
      切换深色
    </button>
  )
}

describe('AuthBackground', () => {
  beforeEach(() => {
    mountAuthBackground.mockClear()
  })

  it('渲染 aria-hidden 的画布层并标注当前变体', () => {
    const { container } = renderProviders(<AuthBackground variant="aurora" />)

    const layer = container.querySelector('.auth-bg-layer')
    expect(layer).toHaveAttribute('aria-hidden', 'true')
    expect(layer).toHaveAttribute('data-variant', 'aurora')
    expect(container.querySelector('canvas.auth-bg-canvas')).toBeInTheDocument()
  })

  it('挂载时把画布与设备 / 主题选项交给引擎', () => {
    const { container } = renderProviders(<AuthBackground variant="rain" />)

    expect(mountAuthBackground).toHaveBeenCalledTimes(1)
    const [canvas, options] = mountAuthBackground.mock.calls[0]
    expect(canvas).toBe(container.querySelector('canvas.auth-bg-canvas'))
    expect(options).toMatchObject({ variant: 'rain', reducedMotion: false })
  })

  it('主题切换后释放旧引擎并按新主题重建', async () => {
    const user = userEvent.setup()
    const { unmount } = renderProviders(
      <>
        <ThemeSwitchProbe />
        <AuthBackground variant="constellation" />
      </>,
    )

    const firstDispose = mountAuthBackground.mock.results[0].value
    expect(mountAuthBackground).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: '切换深色' }))

    expect(firstDispose).toHaveBeenCalledTimes(1)
    expect(mountAuthBackground).toHaveBeenCalledTimes(2)
    expect(mountAuthBackground.mock.calls[1][1]).toMatchObject({ isDark: true })

    unmount()
  })

  it('卸载时调用引擎 dispose', () => {
    const { unmount } = renderProviders(<AuthBackground variant="orbs" />)
    const dispose = mountAuthBackground.mock.results[0].value

    unmount()

    expect(dispose).toHaveBeenCalledTimes(1)
  })
})

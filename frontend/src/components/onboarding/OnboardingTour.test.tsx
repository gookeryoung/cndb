/** OnboardingTour 组件测试：mock driver.js，验证触发条件与完成标记. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen } from '@testing-library/react'
import OnboardingTour from './OnboardingTour'
import { useOnboardingStore } from '@/store/onboarding'
import { renderProviders } from '@/test/render-providers'

const driveMock = vi.fn()
const isActiveMock = vi.fn(() => false)
const destroyCbBox: { onDestroyed?: () => void } = {}

vi.mock('driver.js', () => ({
  driver: vi.fn((config: { onDestroyed?: () => void }) => {
    destroyCbBox.onDestroyed = config?.onDestroyed
    return { drive: driveMock, isActive: isActiveMock }
  }),
}))

function setWindowWidth(w: number) {
  vi.stubGlobal('innerWidth', w)
  act(() => {
    window.dispatchEvent(new Event('resize'))
  })
}

describe('OnboardingTour', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    driveMock.mockClear()
    isActiveMock.mockClear().mockReturnValue(false)
    destroyCbBox.onDestroyed = undefined
    useOnboardingStore.setState({ tourDone: false, tourRequested: false })
    localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('非数据表格页不触发引导', () => {
    setWindowWidth(1280)
    renderProviders(<OnboardingTour />, { route: '/w' })
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(driveMock).not.toHaveBeenCalled()
  })

  it('进入数据表格页且未完成过引导 → 自动启动', () => {
    setWindowWidth(1280)
    renderProviders(<OnboardingTour />, { route: '/w/1/tables/10' })
    expect(driveMock).not.toHaveBeenCalled() // 未到延迟时间
    act(() => {
      vi.advanceTimersByTime(900)
    })
    expect(driveMock).toHaveBeenCalledTimes(1)
  })

  it('已完成过引导（tourDone）→ 不再自动弹出', () => {
    setWindowWidth(1280)
    useOnboardingStore.setState({ tourDone: true })
    renderProviders(<OnboardingTour />, { route: '/w/1/tables/10' })
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(driveMock).not.toHaveBeenCalled()
  })

  it('移动端标记完成且不弹出', () => {
    setWindowWidth(500)
    renderProviders(<OnboardingTour />, { route: '/w/1/tables/10' })
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(driveMock).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().tourDone).toBe(true)
  })

  it('帮助中心重放信号（tourRequested）→ 立即启动并清除信号', () => {
    setWindowWidth(1280)
    useOnboardingStore.setState({ tourRequested: true })
    renderProviders(<OnboardingTour />, { route: '/w' })
    expect(driveMock).toHaveBeenCalledTimes(1)
    expect(useOnboardingStore.getState().tourRequested).toBe(false)
  })

  it('引导销毁（完成或关闭）→ 写入完成标记', () => {
    setWindowWidth(1280)
    renderProviders(<OnboardingTour />, { route: '/w/1/tables/10' })
    act(() => {
      vi.advanceTimersByTime(900)
    })
    act(() => {
      destroyCbBox.onDestroyed?.()
    })
    expect(useOnboardingStore.getState().tourDone).toBe(true)
  })

  it('渲染不产生可见 DOM（纯逻辑组件）', () => {
    setWindowWidth(1280)
    renderProviders(<OnboardingTour />, { route: '/w' })
    expect(screen.queryByText(/cndb/)).not.toBeInTheDocument()
  })
})

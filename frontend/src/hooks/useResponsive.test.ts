/** useResponsive 单元测试 —— 断点判定、SSR 安全、resize 防抖 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BREAKPOINTS, getDeviceType, getResponsiveState, useResponsive } from './useResponsive'

describe('getDeviceType 断点边界', () => {
  it.each([
    [0, 'mobile'],
    [767, 'mobile'],
    [768, 'tablet'],
    [1023, 'tablet'],
    [1024, 'desktop'],
    [1279, 'desktop'],
    [1280, 'desktop'],
    [2560, 'desktop'],
  ])('宽度 %i → %s', (width, expected) => {
    expect(getDeviceType(width)).toBe(expected)
  })

  it('断点常量与 antd 一致', () => {
    expect(BREAKPOINTS).toEqual({ mobile: 768, tablet: 1024, desktop: 1280 })
  })
})

describe('getResponsiveState SSR 安全', () => {
  it('window 未定义时返回桌面默认值', () => {
    // jsdom 下 window 存在；用 vi.stubGlobal 模拟 SSR 场景
    vi.stubGlobal('window', undefined)
    try {
      const state = getResponsiveState()
      expect(state).toEqual({
        deviceType: 'desktop',
        isMobile: false,
        isTablet: false,
        isDesktop: true,
        width: 1280,
        height: 800,
      })
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('window 存在时按 innerWidth/innerHeight 计算', () => {
    vi.stubGlobal('innerWidth', 500)
    vi.stubGlobal('innerHeight', 900)
    try {
      const state = getResponsiveState()
      expect(state.deviceType).toBe('mobile')
      expect(state.isMobile).toBe(true)
      expect(state.width).toBe(500)
      expect(state.height).toBe(900)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

describe('useResponsive hook 行为', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('初始状态与当前窗口一致', () => {
    vi.stubGlobal('innerWidth', 1000)
    vi.stubGlobal('innerHeight', 800)
    try {
      const { result } = renderHook(() => useResponsive())
      expect(result.current.deviceType).toBe('tablet')
      expect(result.current.isTablet).toBe(true)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('resize 事件 100ms 防抖后更新状态', () => {
    const { result } = renderHook(() => useResponsive())
    expect(result.current.deviceType).not.toBe('mobile')

    act(() => {
      vi.stubGlobal('innerWidth', 375)
      window.dispatchEvent(new Event('resize'))
    })
    // 防抖期内不更新
    act(() => {
      vi.advanceTimersByTime(50)
    })
    expect(result.current.deviceType).not.toBe('mobile')
    // 100ms 后更新
    act(() => {
      vi.advanceTimersByTime(60)
    })
    expect(result.current.deviceType).toBe('mobile')
    vi.unstubAllGlobals()
  })

  it('连续 resize 只触发最后一次计算（防抖去重）', () => {
    const spy = vi.spyOn(window, 'addEventListener')
    const { result } = renderHook(() => useResponsive())
    const addCalls = spy.mock.calls.filter(([e]) => e === 'resize').length
    expect(addCalls).toBe(1)

    act(() => {
      vi.stubGlobal('innerWidth', 375)
      window.dispatchEvent(new Event('resize'))
      vi.advanceTimersByTime(50)
      vi.stubGlobal('innerWidth', 1500)
      window.dispatchEvent(new Event('resize'))
      vi.advanceTimersByTime(100)
    })
    expect(result.current.deviceType).toBe('desktop')
    vi.unstubAllGlobals()
    spy.mockRestore()
  })
})

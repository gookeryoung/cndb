/** useDebouncedCallback 单元测试 —— 最后一次调用、参数透传、cancel 与卸载安全 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedCallback } from './useDebouncedCallback'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useDebouncedCallback', () => {
  it('窗口内多次调用只执行最后一次并透传参数', () => {
    const fn = vi.fn()
    const { result } = renderHook(() => useDebouncedCallback(fn, 500))
    const [run] = result.current
    act(() => { run(1); vi.advanceTimersByTime(250); run(2); vi.advanceTimersByTime(250); run(3) })
    act(() => { vi.advanceTimersByTime(500) })
    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn).toHaveBeenCalledWith(3)
  })

  it('ref 更新：pending 执行时调用最新闭包', () => {
    const fn1 = vi.fn()
    const fn2 = vi.fn()
    const { result, rerender } = renderHook(
      ({ f }) => useDebouncedCallback(f, 100),
      { initialProps: { f: fn1 } },
    )
    rerender({ f: fn2 })
    act(() => { result.current[0]() })
    act(() => { vi.advanceTimersByTime(100) })
    expect(fn1).not.toHaveBeenCalled()
    expect(fn2).toHaveBeenCalledTimes(1)
  })

  it('run 重复调用重置计时器', () => {
    const fn = vi.fn()
    const { result } = renderHook(() => useDebouncedCallback(fn, 500))
    const [run] = result.current
    act(() => { run() })
    act(() => { vi.advanceTimersByTime(400) })
    act(() => { run() })
    act(() => { vi.advanceTimersByTime(400) })
    expect(fn).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(100) })
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('cancel 取消 pending 调用', () => {
    const fn = vi.fn()
    const { result } = renderHook(() => useDebouncedCallback(fn, 500))
    const [run, cancel] = result.current
    act(() => { run() })
    act(() => { cancel() })
    act(() => { vi.advanceTimersByTime(1000) })
    expect(fn).not.toHaveBeenCalled()
  })

  it('卸载时自动取消 pending 调用', () => {
    const fn = vi.fn()
    const { result, unmount } = renderHook(() => useDebouncedCallback(fn, 500))
    act(() => { result.current[0]() })
    unmount()
    act(() => { vi.advanceTimersByTime(1000) })
    expect(fn).not.toHaveBeenCalled()
  })

  it('相同 delayMs 下 run/cancel 引用稳定', () => {
    const fn = vi.fn()
    const { result, rerender } = renderHook(() => useDebouncedCallback(fn, 500))
    const [firstRun, firstCancel] = result.current
    rerender()
    expect(result.current[0]).toBe(firstRun)
    expect(result.current[1]).toBe(firstCancel)
  })
})

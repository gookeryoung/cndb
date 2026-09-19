/** useDebouncedValue 单元测试 —— 防抖窗口、最终值、卸载安全 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedValue } from './useDebouncedValue'

beforeEach(() => {
    vi.useFakeTimers()
})

afterEach(() => {
    vi.useRealTimers()
})

describe('useDebouncedValue', () => {
    it('初始返回源值', () => {
        const { result } = renderHook(() => useDebouncedValue('a', 300))
        expect(result.current).toBe('a')
    })

    it('窗口内未到期不更新', () => {
        const { result, rerender } = renderHook(
            ({ v }) => useDebouncedValue(v, 300),
            { initialProps: { v: 'a' } },
        )
        rerender({ v: 'b' })
        act(() => { vi.advanceTimersByTime(200) })
        expect(result.current).toBe('a')
    })

    it('到期后更新为最新值', () => {
        const { result, rerender } = renderHook(
            ({ v }) => useDebouncedValue(v, 300),
            { initialProps: { v: 'a' } },
        )
        rerender({ v: 'b' })
        act(() => { vi.advanceTimersByTime(300) })
        expect(result.current).toBe('b')
    })

    it('窗口内多次变更只取最终值（计时器重置）', () => {
        const { result, rerender } = renderHook(
            ({ v }) => useDebouncedValue(v, 300),
            { initialProps: { v: 'a' } },
        )
        rerender({ v: 'b' })
        act(() => { vi.advanceTimersByTime(200) })
        rerender({ v: 'c' })
        act(() => { vi.advanceTimersByTime(200) })
        expect(result.current).toBe('a')
        act(() => { vi.advanceTimersByTime(100) })
        expect(result.current).toBe('c')
    })

    it('对象引用值同样按最新引用更新', () => {
        const { result, rerender } = renderHook(
            ({ v }) => useDebouncedValue(v, 100),
            { initialProps: { v: { n: 1 } } },
        )
        const next = { n: 2 }
        rerender({ v: next })
        act(() => { vi.advanceTimersByTime(100) })
        expect(result.current).toBe(next)
    })

    it('delayMs=0 仍在微任务后的定时器边界生效', () => {
        const { result, rerender } = renderHook(
            ({ v }) => useDebouncedValue(v, 0),
            { initialProps: { v: 'a' } },
        )
        rerender({ v: 'b' })
        act(() => { vi.advanceTimersByTime(0) })
        expect(result.current).toBe('b')
    })

    it('卸载后不再触发更新', () => {
        const { result, rerender, unmount } = renderHook(
            ({ v }) => useDebouncedValue(v, 300),
            { initialProps: { v: 'a' } },
        )
        rerender({ v: 'b' })
        unmount()
        act(() => { vi.advanceTimersByTime(1000) })
        expect(result.current).toBe('a')
    })
})

/** 未保存编辑守卫 + 可重试错误条（路线图 0141 P0-3）测试. */

import { describe, expect, it, vi, afterEach } from 'vitest'
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'

import GridErrorBar from './GridErrorBar'
import { UNSAVED_LEAVE_MESSAGE, useUnsavedGuard } from './useUnsavedGuard'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useUnsavedGuard', () => {
  it('脏状态下 beforeunload 被拦截（preventDefault + returnValue）', () => {
    const { result, rerender } = renderHook(({ dirty }) => useUnsavedGuard(dirty), {
      initialProps: { dirty: false },
    })
    expect(result.current.dirty).toBe(false)

    rerender({ dirty: true })
    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    const preventDefault = vi.spyOn(event, 'preventDefault')
    act(() => {
      window.dispatchEvent(event)
    })
    expect(preventDefault).toHaveBeenCalled()
    // 按规范：preventDefault 后 returnValue 归为 false（即"取消离开"）
    expect(event.defaultPrevented).toBe(true)
    expect(event.returnValue).toBe(false)
  })

  it('干净状态下不拦截 beforeunload', () => {
    renderHook(() => useUnsavedGuard(false))
    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    const preventDefault = vi.spyOn(event, 'preventDefault')
    act(() => {
      window.dispatchEvent(event)
    })
    expect(preventDefault).not.toHaveBeenCalled()
  })

  it('confirmLeave：脏状态走 confirm，用户取消则不放行；force 跳过确认', () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { result, rerender } = renderHook(({ dirty }) => useUnsavedGuard(dirty), {
      initialProps: { dirty: true },
    })

    expect(result.current.confirmLeave()).toBe(false)
    expect(confirmSpy).toHaveBeenCalledWith(UNSAVED_LEAVE_MESSAGE)
    expect(result.current.confirmLeave(true)).toBe(true)

    confirmSpy.mockReturnValue(true)
    expect(result.current.confirmLeave()).toBe(true)

    rerender({ dirty: false })
    confirmSpy.mockClear()
    expect(result.current.confirmLeave()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('卸载后不再拦截（监听器已解绑）', () => {
    const { unmount } = renderHook(() => useUnsavedGuard(true))
    unmount()
    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    const preventDefault = vi.spyOn(event, 'preventDefault')
    act(() => {
      window.dispatchEvent(event)
    })
    expect(preventDefault).not.toHaveBeenCalled()
  })
})

describe('GridErrorBar', () => {
  it('无错误时不渲染', () => {
    const { container } = render(<GridErrorBar error={null} onDismiss={() => { }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('展示错误文案并支持重试 / 忽略', () => {
    const retry = vi.fn()
    const dismiss = vi.fn()
    render(<GridErrorBar error={{ message: '网络错误，请重试', retry }} onDismiss={dismiss} />)

    expect(screen.getByTestId('grid-error-bar-message')).toHaveTextContent('网络错误，请重试')
    fireEvent.click(screen.getByTestId('grid-error-bar-retry'))
    expect(retry).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByTestId('grid-error-bar-dismiss'))
    expect(dismiss).toHaveBeenCalledTimes(1)
  })

  it('重试中按钮进入 loading 且不可重复点击', () => {
    const retry = vi.fn()
    render(<GridErrorBar error={{ message: '失败', retry }} onDismiss={() => { }} retrying />)
    const button = screen.getByTestId('grid-error-bar-retry')
    expect(button.className).toContain('ant-btn-loading')
    fireEvent.click(button)
    expect(retry).not.toHaveBeenCalled()
  })
})

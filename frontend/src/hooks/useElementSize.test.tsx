/** useElementSize 组件测试 —— 挂载即测、双通道更新、卸载清理 */
import { act, render, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useElementSize } from './useElementSize'
import type { ElementSize } from './useElementSize'

/** 受控 ResizeObserver stub：捕获实例与回调，测试中手动触发 */
class MockResizeObserver {
  static instances: MockResizeObserver[] = []
  cb: ResizeObserverCallback
  observe = vi.fn()
  disconnect = vi.fn()
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb
    MockResizeObserver.instances.push(this)
  }
}

/** 把 jsdom 元素的 clientWidth/clientHeight mock 为固定值（setup 的 restoreMocks 自动还原） */
function mockElementSize(width: number, height: number) {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(width)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(height)
}

/** 探针组件：把 hook 返回的 size 暴露到外部 ref，并绑定 ref 到真实 div */
function Probe({ sizeRef, initial }: {
  sizeRef: { current: ElementSize | null }
  initial?: ElementSize
}) {
  const [ref, size] = useElementSize<HTMLDivElement>(initial)
  sizeRef.current = size
  return <div ref={ref} data-testid="probe" />
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', MockResizeObserver)
  MockResizeObserver.instances = []
  mockElementSize(640, 480)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useElementSize', () => {
  it('ref 未挂载时保持初始值', () => {
    const { result } = renderHook(() => useElementSize<HTMLDivElement>({ width: 800, height: 400 }))
    expect(result.current[1]).toEqual({ width: 800, height: 400 })
    expect(result.current[0]).not.toBeNull()
  })

  it('挂载即测量元素尺寸', () => {
    const sizeRef = { current: null as ElementSize | null }
    render(<Probe sizeRef={sizeRef} initial={{ width: 800, height: 400 }} />)
    expect(sizeRef.current).toEqual({ width: 640, height: 480 })
  })

  it('ResizeObserver 回调触发尺寸更新', () => {
    const sizeRef = { current: null as ElementSize | null }
    render(<Probe sizeRef={sizeRef} initial={{ width: 800, height: 400 }} />)
    const instance = MockResizeObserver.instances.at(-1)
    expect(instance).toBeDefined()
    mockElementSize(1000, 720)
    act(() => { instance!.cb([] as unknown as ResizeObserverEntry[], instance as unknown as ResizeObserver) })
    expect(sizeRef.current).toEqual({ width: 1000, height: 720 })
  })

  it('window resize 触发尺寸更新', () => {
    const sizeRef = { current: null as ElementSize | null }
    render(<Probe sizeRef={sizeRef} initial={{ width: 800, height: 400 }} />)
    mockElementSize(640, 900)
    act(() => { window.dispatchEvent(new Event('resize')) })
    expect(sizeRef.current).toEqual({ width: 640, height: 900 })
  })

  it('卸载时断开 ResizeObserver 并移除 resize 监听', () => {
    const sizeRef = { current: null as ElementSize | null }
    const { unmount } = render(<Probe sizeRef={sizeRef} initial={{ width: 800, height: 400 }} />)
    const instance = MockResizeObserver.instances.at(-1)!
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    unmount()
    expect(instance.disconnect).toHaveBeenCalledTimes(1)
    expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function))
  })
})

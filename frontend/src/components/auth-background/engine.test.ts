import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mountAuthBackground } from './engine'

function createFakeContext() {
  const gradient = { addColorStop: vi.fn() }
  return {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    createRadialGradient: vi.fn(() => gradient),
    createLinearGradient: vi.fn(() => gradient),
    setTransform: vi.fn(),
    globalAlpha: 1,
    globalCompositeOperation: 'source-over' as GlobalCompositeOperation,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    font: '',
    textBaseline: 'top' as CanvasTextBaseline,
  }
}

function createCanvas(ctx: unknown) {
  const canvas = document.createElement('canvas')
  Object.defineProperty(canvas, 'getContext', { configurable: true, value: () => ctx })
  Object.defineProperty(canvas, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      width: 320,
      height: 180,
      top: 0,
      left: 0,
      right: 320,
      bottom: 180,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }),
  })
  return canvas
}

const paletteStyle = {
  '--cn-auth-accent': '#22d3ee',
  '--cn-auth-accent-alt': '#a855f7',
  '--cn-auth-ink': '#dbe4f3',
}

let frameCallbacks: Map<number, FrameRequestCallback>
let sequence = 0

function takeFrame(): FrameRequestCallback {
  const entries = [...frameCallbacks.entries()]
  const last = entries[entries.length - 1]
  if (!last) throw new Error('没有待执行的 rAF')
  frameCallbacks.delete(last[0])
  return last[1]
}

beforeEach(() => {
  frameCallbacks = new Map()
  sequence = 0
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => {
    sequence += 1
    frameCallbacks.set(sequence, callback)
    return sequence
  })
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(id => {
    frameCallbacks.delete(id)
  })
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) =>
      (paletteStyle as Record<string, string>)[name] ?? '',
  } as CSSStyleDeclaration)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const baseOptions = {
  isMobile: false,
  reducedMotion: false,
}

describe('mountAuthBackground', () => {
  it('启动单 rAF 循环并绘制首帧，dispose 后停止', () => {
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, baseOptions)

    expect(ctx.clearRect).toHaveBeenCalledTimes(1)
    expect(frameCallbacks.size).toBe(1)

    dispose()
    expect(frameCallbacks.size).toBe(0)
    expect(() => dispose()).not.toThrow()
  })

  it('没有 2D context 时降级为 noop', () => {
    const canvas = createCanvas(null)
    const dispose = mountAuthBackground(canvas, baseOptions)

    expect(window.requestAnimationFrame).not.toHaveBeenCalled()
    expect(() => dispose()).not.toThrow()
  })

  it('取色失败时降级为 noop', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: () => '',
    } as unknown as CSSStyleDeclaration)

    const canvas = createCanvas(createFakeContext())
    mountAuthBackground(canvas, baseOptions)

    expect(window.requestAnimationFrame).not.toHaveBeenCalled()
  })

  it('reduced-motion 只画静态首帧，不启动 rAF', () => {
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, { ...baseOptions, reducedMotion: true })

    expect(ctx.clearRect).toHaveBeenCalledTimes(1)
    expect(window.requestAnimationFrame).not.toHaveBeenCalled()
    dispose()
  })

  it('页面隐藏时暂停，恢复后重启', () => {
    let hidden = false
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })

    const canvas = createCanvas(createFakeContext())
    const dispose = mountAuthBackground(canvas, baseOptions)
    expect(frameCallbacks.size).toBe(1)

    hidden = true
    document.dispatchEvent(new Event('visibilitychange'))
    expect(frameCallbacks.size).toBe(0)

    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))
    expect(frameCallbacks.size).toBe(1)

    dispose()
  })

  it('resize 事件 150ms 节流后重新测量', () => {
    vi.useFakeTimers()
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, baseOptions)
    expect(ctx.setTransform).toHaveBeenCalledTimes(1)

    window.dispatchEvent(new Event('resize'))
    expect(ctx.setTransform).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(150)
    expect(ctx.setTransform).toHaveBeenCalledTimes(2)

    dispose()
  })

  it('dispose 后 resize 不再触发测量', () => {
    vi.useFakeTimers()
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, baseOptions)
    dispose()

    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(150)
    expect(ctx.setTransform).toHaveBeenCalledTimes(1)
  })

  it('移动端按 30fps 跳帧', () => {
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, { ...baseOptions, isMobile: true })
    expect(ctx.clearRect).toHaveBeenCalledTimes(1)

    takeFrame()(16)
    expect(ctx.clearRect).toHaveBeenCalledTimes(1)

    takeFrame()(40)
    expect(ctx.clearRect).toHaveBeenCalledTimes(2)

    dispose()
  })
})

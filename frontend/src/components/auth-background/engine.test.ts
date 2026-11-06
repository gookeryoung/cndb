import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mountAuthBackground } from './engine'

function createFakeContext() {
  return {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    setTransform: vi.fn(),
    globalAlpha: 1,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
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

beforeEach(() => {
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) =>
      (paletteStyle as Record<string, string>)[name] ?? '',
  } as CSSStyleDeclaration)
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 })
})

describe('mountAuthBackground', () => {
  it('挂载时只绘制一次静态晶格，不启动 rAF', () => {
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, { isMobile: false })

    expect(ctx.clearRect).toHaveBeenCalledTimes(1)
    expect(ctx.stroke).toHaveBeenCalledTimes(1)
    expect(ctx.arc).toHaveBeenCalled()
    expect(window.requestAnimationFrame).not.toHaveBeenCalled()
    expect(canvas.width).toBe(320)
    expect(canvas.height).toBe(180)

    dispose()
  })

  it('没有 2D context 时降级为 noop', () => {
    const canvas = createCanvas(null)
    const dispose = mountAuthBackground(canvas, { isMobile: false })

    expect(() => dispose()).not.toThrow()
    expect(window.requestAnimationFrame).not.toHaveBeenCalled()
  })

  it('取色失败时降级为 noop', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: () => '',
    } as unknown as CSSStyleDeclaration)

    const ctx = createFakeContext()
    mountAuthBackground(createCanvas(ctx), { isMobile: false })

    expect(ctx.stroke).not.toHaveBeenCalled()
  })

  it('桌面 DPR 封顶 2、移动端封顶 1.5', () => {
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 3 })

    const desktopCtx = createFakeContext()
    const desktopCanvas = createCanvas(desktopCtx)
    mountAuthBackground(desktopCanvas, { isMobile: false })
    expect(desktopCanvas.width).toBe(640)
    expect(desktopCanvas.height).toBe(360)

    const mobileCtx = createFakeContext()
    const mobileCanvas = createCanvas(mobileCtx)
    mountAuthBackground(mobileCanvas, { isMobile: true })
    expect(mobileCanvas.width).toBe(480)
    expect(mobileCanvas.height).toBe(270)
  })

  it('resize 事件 150ms 节流后重新绘制一次', () => {
    vi.useFakeTimers()
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, { isMobile: false })
    expect(ctx.setTransform).toHaveBeenCalledTimes(1)

    window.dispatchEvent(new Event('resize'))
    expect(ctx.setTransform).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(150)
    expect(ctx.setTransform).toHaveBeenCalledTimes(2)

    dispose()
  })

  it('dispose 后 resize 不再触发重绘，且可重复调用', () => {
    vi.useFakeTimers()
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    const dispose = mountAuthBackground(canvas, { isMobile: false })
    dispose()

    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(150)
    expect(ctx.setTransform).toHaveBeenCalledTimes(1)
    expect(() => dispose()).not.toThrow()
  })

  it('0 尺寸时跳过绘制，等待后续 resize', () => {
    const ctx = createFakeContext()
    const canvas = createCanvas(ctx)
    Object.defineProperty(canvas, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, x: 0, y: 0 }),
    })

    const dispose = mountAuthBackground(canvas, { isMobile: false })
    expect(ctx.clearRect).not.toHaveBeenCalled()
    dispose()
  })
})

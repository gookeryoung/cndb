import { describe, expect, it, vi } from 'vitest'

import { createFlowField, noise2 } from './flowfield'
import type { FrameContext } from './types'

function createFakeContext() {
  const colorStops: Array<{ offset: number; color: string }> = []
  const gradient = {
    addColorStop: vi.fn((offset: number, color: string) => {
      colorStops.push({ offset, color })
    }),
  }
  return {
    colorStops,
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    createLinearGradient: vi.fn(() => gradient),
    setTransform: vi.fn(),
    globalAlpha: 1,
    globalCompositeOperation: 'source-over' as GlobalCompositeOperation,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
  }
}

function buildFrame(
  ctx: ReturnType<typeof createFakeContext>,
  overrides: Partial<FrameContext> = {},
): FrameContext {
  return {
    ctx: ctx as unknown as CanvasRenderingContext2D,
    width: 320,
    height: 200,
    palette: { accent: '#22d3ee', accentAlt: '#a855f7', ink: '#dbe4f3' },
    isMobile: false,
    pointer: { x: 0.4, y: -0.3 },
    ...overrides,
  }
}

describe('Perlin 流场粒子', () => {
  it('resize 后 frame 产生一次流线描边且坐标有限', () => {
    const flow = createFlowField(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    flow.resize(frame)
    flow.frame(frame, 0)

    expect(ctx.clearRect).toHaveBeenCalled()
    expect(ctx.stroke).toHaveBeenCalledTimes(1)
    expect(ctx.moveTo.mock.calls.length).toBeGreaterThan(0)
    // 每个粒子一条多段尾迹，保证稳态下是流线而不是亚像素短点
    expect(ctx.lineTo.mock.calls.length).toBeGreaterThanOrEqual(
      ctx.moveTo.mock.calls.length * 10,
    )

    const numericArgs = [...ctx.moveTo.mock.calls.flat(), ...ctx.lineTo.mock.calls.flat()].filter(
      (value): value is number => typeof value === 'number',
    )
    expect(numericArgs.length).toBeGreaterThan(0)
    expect(numericArgs.every(Number.isFinite)).toBe(true)
  })

  it('0 尺寸不绘制也不抛错', () => {
    const flow = createFlowField(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx, { width: 0, height: 0 })

    flow.resize(frame)
    expect(() => flow.frame(frame, 0)).not.toThrow()
    expect(ctx.clearRect).not.toHaveBeenCalled()
    expect(ctx.stroke).not.toHaveBeenCalled()
  })

  it('移动端可绘制且不使用指针扰动', () => {
    const flow = createFlowField(true)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx, { isMobile: true, pointer: { x: 1, y: 1 } })

    flow.resize(frame)
    expect(() => flow.frame(frame, 500)).not.toThrow()
    expect(ctx.stroke).toHaveBeenCalledTimes(1)
  })

  it('首帧预热后每帧只描边一次', () => {
    const flow = createFlowField(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    flow.resize(frame)
    flow.frame(frame, 0)
    expect(ctx.stroke).toHaveBeenCalledTimes(1)

    flow.frame(frame, 16)
    expect(ctx.stroke).toHaveBeenCalledTimes(2)
  })

  it('青紫渐变包含青 → 紫 → 青三个色标', () => {
    const flow = createFlowField(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    flow.resize(frame)
    flow.frame(frame, 0)

    expect(ctx.createLinearGradient).toHaveBeenCalledTimes(1)
    expect(ctx.colorStops).toEqual([
      { offset: 0, color: 'rgba(34, 211, 238, 0.55)' },
      { offset: 0.5, color: 'rgba(168, 85, 247, 0.6)' },
      { offset: 1, color: 'rgba(34, 211, 238, 0.55)' },
    ])
  })

  it('固定种子下两次实例的流线一致', () => {
    const first = createFakeContext()
    const firstFrame = buildFrame(first)
    const firstFlow = createFlowField(false)
    firstFlow.resize(firstFrame)
    firstFlow.frame(firstFrame, 0)

    const second = createFakeContext()
    const secondFrame = buildFrame(second)
    const secondFlow = createFlowField(false)
    secondFlow.resize(secondFrame)
    secondFlow.frame(secondFrame, 0)

    expect(second.moveTo.mock.calls).toEqual(first.moveTo.mock.calls)
    expect(second.lineTo.mock.calls).toEqual(first.lineTo.mock.calls)
  })

  it('Perlin 噪声确定且在 -1..1 内', () => {
    const samples = [
      noise2(0.5, 0.5),
      noise2(12.3, -4.7),
      noise2(-100.25, 88.125),
      noise2(0.5, 0.5),
    ]
    expect(samples.every(Number.isFinite)).toBe(true)
    expect(samples.every(value => value >= -1 && value <= 1)).toBe(true)
    expect(samples[0]).toBe(samples[3])
  })
})

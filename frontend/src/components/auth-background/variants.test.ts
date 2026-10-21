import { describe, expect, it, vi } from 'vitest'

import type { BackgroundVariant, FrameContext } from './types'
import { createAurora } from './variants/aurora'
import { createConstellation } from './variants/constellation'
import { createNebula } from './variants/nebula'
import { createOrbs } from './variants/orbs'
import { createRain } from './variants/rain'

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

function buildFrame(
  ctx: ReturnType<typeof createFakeContext>,
  overrides: Partial<FrameContext> = {},
): FrameContext {
  return {
    ctx: ctx as unknown as CanvasRenderingContext2D,
    width: 320,
    height: 200,
    palette: { brand: '#3b82f6', text: '#1f2937', bg: '#f5f7fa' },
    isDark: false,
    isMobile: false,
    pointer: { x: 0.4, y: -0.3 },
    ...overrides,
  }
}

const CASES: Array<[string, (isMobile: boolean) => BackgroundVariant]> = [
  ['constellation', createConstellation],
  ['nebula', createNebula],
  ['aurora', createAurora],
  ['rain', createRain],
  ['orbs', createOrbs],
]

describe.each(CASES)('%s 变体', (_name, factory) => {
  it('resize 后 frame 产生绘制操作且坐标有限', () => {
    const variant = factory(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    variant.resize(frame)
    variant.frame(frame, 240)

    expect(ctx.clearRect).toHaveBeenCalled()
    const painted =
      ctx.fill.mock.calls.length +
      ctx.stroke.mock.calls.length +
      ctx.fillRect.mock.calls.length +
      ctx.fillText.mock.calls.length
    expect(painted).toBeGreaterThan(0)

    const numericArgs = [
      ...ctx.arc.mock.calls.flat(),
      ...ctx.moveTo.mock.calls.flat(),
      ...ctx.lineTo.mock.calls.flat(),
      ...ctx.fillRect.mock.calls.flat(),
      ...ctx.fillText.mock.calls.flat(),
    ].filter((value): value is number => typeof value === 'number')
    expect(numericArgs.length).toBeGreaterThan(0)
    expect(numericArgs.every(Number.isFinite)).toBe(true)
  })

  it('0 尺寸不绘制也不抛错', () => {
    const variant = factory(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx, { width: 0, height: 0 })

    variant.resize(frame)
    expect(() => variant.frame(frame, 0)).not.toThrow()
    expect(ctx.clearRect).not.toHaveBeenCalled()
  })

  it('移动端与深色主题可绘制', () => {
    const variant = factory(true)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx, { isMobile: true, isDark: true })

    variant.resize(frame)
    expect(() => variant.frame(frame, 500)).not.toThrow()
  })
})

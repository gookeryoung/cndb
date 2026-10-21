import { describe, expect, it, vi } from 'vitest'

import { createGalaxy } from './galaxy'
import type { FrameContext } from './types'

function createFakeContext() {
  const colorStops: Array<{ offset: number; color: string }> = []
  const gradient = {
    addColorStop: vi.fn((offset: number, color: string) => {
      colorStops.push({ offset, color })
    }),
  }
  const styles: string[] = []
  let fillStyle: string | CanvasGradient | CanvasPattern = ''
  return {
    colorStops,
    styles,
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    createRadialGradient: vi.fn(() => gradient),
    globalAlpha: 1,
    globalCompositeOperation: 'source-over' as GlobalCompositeOperation,
    get fillStyle() {
      return fillStyle
    },
    set fillStyle(value: string | CanvasGradient | CanvasPattern) {
      fillStyle = value
      styles.push(typeof value === 'string' ? value : 'gradient')
    },
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

describe('宇宙星系', () => {
  it('resize 后 frame 先铺每座星系的外晕与核球辉光再画星点，坐标有限', () => {
    const galaxy = createGalaxy(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    galaxy.resize(frame)
    galaxy.frame(frame, 0)

    expect(ctx.clearRect).toHaveBeenCalledTimes(1)
    // 桌面 3 座星系 ×（外晕 + 核球）
    expect(ctx.createRadialGradient).toHaveBeenCalledTimes(6)
    // 6 层渐变铺底 + 1600 星点（亮星额外一层柔光）
    expect(ctx.fillRect.mock.calls.length).toBeGreaterThanOrEqual(1606)

    // 首个填充是主星系的裁剪光晕，必须落在画布内
    const [left, top, drawWidth, drawHeight] = ctx.fillRect.mock.calls[0]
    expect(left).toBeGreaterThanOrEqual(0)
    expect(top).toBeGreaterThanOrEqual(0)
    expect(left + drawWidth).toBeLessThanOrEqual(320)
    expect(top + drawHeight).toBeLessThanOrEqual(200)

    const numericArgs = ctx.fillRect.mock.calls.flat().filter(
      (value): value is number => typeof value === 'number',
    )
    expect(numericArgs.length).toBeGreaterThan(0)
    expect(numericArgs.every(Number.isFinite)).toBe(true)
  })

  it('每座星系的外晕与核球辉光由多层色标组成，并按色相换主色', () => {
    const galaxy = createGalaxy(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    galaxy.resize(frame)
    galaxy.frame(frame, 0)

    // 3 座星系 ×（外晕 5 + 核球 3）
    expect(ctx.colorStops).toHaveLength(24)

    // 主星系以青为主色
    expect(ctx.colorStops.slice(0, 8)).toEqual([
      { offset: 0, color: 'rgba(219, 228, 243, 0.12)' },
      { offset: 0.16, color: 'rgba(34, 211, 238, 0.24)' },
      { offset: 0.42, color: 'rgba(168, 85, 247, 0.12)' },
      { offset: 0.74, color: 'rgba(34, 211, 238, 0.06)' },
      { offset: 1, color: 'transparent' },
      { offset: 0, color: 'rgba(219, 228, 243, 0.3)' },
      { offset: 0.45, color: 'rgba(34, 211, 238, 0.18)' },
      { offset: 1, color: 'transparent' },
    ])

    // 次星系以紫为主色，与主星系形成冷暖对比
    expect(ctx.colorStops.slice(8, 16)).toEqual([
      { offset: 0, color: 'rgba(219, 228, 243, 0.12)' },
      { offset: 0.16, color: 'rgba(168, 85, 247, 0.24)' },
      { offset: 0.42, color: 'rgba(34, 211, 238, 0.12)' },
      { offset: 0.74, color: 'rgba(168, 85, 247, 0.06)' },
      { offset: 1, color: 'transparent' },
      { offset: 0, color: 'rgba(219, 228, 243, 0.3)' },
      { offset: 0.45, color: 'rgba(168, 85, 247, 0.18)' },
      { offset: 1, color: 'transparent' },
    ])
  })

  it('星点按青 / 紫 / 亮白三组批量着色，每座星系只切换 3 次', () => {
    const galaxy = createGalaxy(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    galaxy.resize(frame)
    galaxy.frame(frame, 0)

    // 每座星系：外晕 + 核球两层渐变，随后按组切 3 次颜色
    expect(ctx.styles).toEqual([
      'gradient',
      'gradient',
      'rgba(34, 211, 238, 0.72)',
      'rgba(168, 85, 247, 0.66)',
      'rgba(219, 228, 243, 0.78)',
      'gradient',
      'gradient',
      'rgba(34, 211, 238, 0.72)',
      'rgba(168, 85, 247, 0.66)',
      'rgba(219, 228, 243, 0.78)',
      'gradient',
      'gradient',
      'rgba(34, 211, 238, 0.72)',
      'rgba(168, 85, 247, 0.66)',
      'rgba(219, 228, 243, 0.78)',
    ])
  })

  it('0 尺寸不绘制也不抛错', () => {
    const galaxy = createGalaxy(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx, { width: 0, height: 0 })

    galaxy.resize(frame)
    expect(() => galaxy.frame(frame, 0)).not.toThrow()
    expect(ctx.clearRect).not.toHaveBeenCalled()
    expect(ctx.fillRect).not.toHaveBeenCalled()
  })

  it('移动端只保留两座星系并忽略指针', () => {
    const galaxy = createGalaxy(true)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx, {
      isMobile: true,
      pointer: { x: 1, y: 1 },
      width: 375,
      height: 700,
    })

    galaxy.resize(frame)
    galaxy.frame(frame, 500)

    expect(ctx.createRadialGradient).toHaveBeenCalledTimes(4)
    // 2 座星系共 700 星点 + 4 层渐变
    expect(ctx.fillRect.mock.calls.length).toBeGreaterThanOrEqual(704)
  })

  it('星系渐变跨帧复用，不重复创建', () => {
    const galaxy = createGalaxy(false)
    const ctx = createFakeContext()
    const frame = buildFrame(ctx)

    galaxy.resize(frame)
    galaxy.frame(frame, 0)
    galaxy.frame(frame, 16)

    expect(ctx.createRadialGradient).toHaveBeenCalledTimes(6)
  })

  it('固定种子下两次实例的星点一致', () => {
    const first = createFakeContext()
    const firstFrame = buildFrame(first)
    const firstGalaxy = createGalaxy(false)
    firstGalaxy.resize(firstFrame)
    firstGalaxy.frame(firstFrame, 0)

    const second = createFakeContext()
    const secondFrame = buildFrame(second)
    const secondGalaxy = createGalaxy(false)
    secondGalaxy.resize(secondFrame)
    secondGalaxy.frame(secondFrame, 0)

    expect(second.fillRect.mock.calls).toEqual(first.fillRect.mock.calls)
  })

  it('桌面指针改变星系中心形成视差', () => {
    const left = createFakeContext()
    const leftFrame = buildFrame(left, { pointer: { x: -1, y: 0 } })
    const leftGalaxy = createGalaxy(false)
    leftGalaxy.resize(leftFrame)
    leftGalaxy.frame(leftFrame, 0)

    const right = createFakeContext()
    const rightFrame = buildFrame(right, { pointer: { x: 1, y: 0 } })
    const rightGalaxy = createGalaxy(false)
    rightGalaxy.resize(rightFrame)
    rightGalaxy.frame(rightFrame, 0)

    expect(right.fillRect.mock.calls[2][0]).not.toBe(left.fillRect.mock.calls[2][0])
  })
})

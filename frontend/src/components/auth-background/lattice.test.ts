import { describe, expect, it, vi } from 'vitest'

import { drawLattice, latticeCell } from './lattice'
import type { LatticeFrame } from './types'

function createFakeContext() {
  return {
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    globalAlpha: 1,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
  }
}

const palette = { accent: '#22d3ee', accentAlt: '#a855f7', ink: '#dbe4f3' }

function buildFrame(
  ctx: ReturnType<typeof createFakeContext>,
  overrides: Partial<LatticeFrame> = {},
): LatticeFrame {
  return {
    ctx: ctx as unknown as CanvasRenderingContext2D,
    width: 320,
    height: 180,
    dpr: 1,
    palette,
    isMobile: false,
    ...overrides,
  }
}

describe('静态晶格', () => {
  it('绘制六边形晶格与青紫结点', () => {
    const lattice = createFakeContext()
    drawLattice(buildFrame(lattice))

    // 每个六边形 1 次 moveTo + 5 次 lineTo
    expect(lattice.moveTo.mock.calls.length).toBeGreaterThan(0)
    expect(lattice.lineTo.mock.calls.length).toBe(lattice.moveTo.mock.calls.length * 5)
    expect(lattice.stroke).toHaveBeenCalledTimes(1)
    expect(lattice.arc).toHaveBeenCalled()
    expect(lattice.fill).toHaveBeenCalled()
  })

  it('线宽与点半径随 DPR 放大，坐标全部在有限范围内', () => {
    const ctx = createFakeContext()
    drawLattice(buildFrame(ctx, { dpr: 2 }))

    expect(ctx.lineWidth).toBeGreaterThanOrEqual(1)
    const numeric = [...ctx.moveTo.mock.calls.flat(), ...ctx.lineTo.mock.calls.flat()].filter(
      (value): value is number => typeof value === 'number',
    )
    expect(numeric.length).toBeGreaterThan(0)
    expect(numeric.every(Number.isFinite)).toBe(true)
    // 允许最多一个六边形半径的溢出（边缘裁切）
    expect(Math.min(...numeric)).toBeGreaterThan(-latticeCell(false) * 2 * 2)
    expect(Math.max(...numeric)).toBeLessThan(320 * 2 + latticeCell(false) * 2 * 2)
  })

  it('0 尺寸不绘制也不抛错', () => {
    const ctx = createFakeContext()
    expect(() => drawLattice(buildFrame(ctx, { width: 0 }))).not.toThrow()
    expect(ctx.stroke).not.toHaveBeenCalled()
    expect(ctx.arc).not.toHaveBeenCalled()
  })

  it('同样参数下两次绘制完全一致（确定性）', () => {
    const first = createFakeContext()
    drawLattice(buildFrame(first))
    const second = createFakeContext()
    drawLattice(buildFrame(second))

    expect(second.moveTo.mock.calls).toEqual(first.moveTo.mock.calls)
    expect(second.lineTo.mock.calls).toEqual(first.lineTo.mock.calls)
    expect(second.arc.mock.calls).toEqual(first.arc.mock.calls)
  })

  it('移动端晶格更密（同尺寸下六边形更多）', () => {
    const desktop = createFakeContext()
    drawLattice(buildFrame(desktop))
    const mobile = createFakeContext()
    drawLattice(buildFrame(mobile, { isMobile: true }))

    expect(mobile.moveTo.mock.calls.length).toBeGreaterThan(desktop.moveTo.mock.calls.length)
  })

  it('颜色只来自色板 token', () => {
    const ctx = createFakeContext()
    drawLattice(buildFrame(ctx))

    expect(ctx.strokeStyle).toBe('rgba(219, 228, 243, 0.085)')
    expect(String(ctx.fillStyle)).toMatch(/^rgba\(/)
  })
})

/** dashboard 布局纯函数单元测试（ADR 0023 P0：clamp / compact / 窄屏塌陷）. */
import { describe, expect, it } from 'vitest'
import {
  DASHBOARD_COLS, DASHBOARD_MAX_H, collapseNarrow, compact, normalizeLayout, toGridStyle, clampBox,
  type WidgetBox,
} from './dashboardLayout'

const box = (id: string, x: number, y: number, w: number, h: number): WidgetBox => ({ id, x, y, w, h })

describe('clampBox', () => {
  it('宽度收敛到 1..12，X 不越右边界', () => {
    expect(clampBox(box('a', 20, 0, 20, 3))).toEqual(box('a', 0, 0, DASHBOARD_COLS, 3))
    expect(clampBox(box('b', 10, 0, 4, 3))).toEqual(box('b', 8, 0, 4, 3))
  })

  it('高度收敛到 1..20，Y 不为负', () => {
    expect(clampBox(box('a', 0, -5, 2, 0))).toEqual(box('a', 0, 0, 2, 1))
    expect(clampBox(box('b', 0, 0, 2, 99))).toEqual(box('b', 0, 0, 2, DASHBOARD_MAX_H))
  })

  it('非整数坐标截断为整数', () => {
    expect(clampBox(box('a', 1.8, 2.9, 3.4, 4.6))).toEqual(box('a', 1, 2, 3, 4))
  })
})

describe('compact', () => {
  it('把下方带洞的块上浮到最小不重叠 Y', () => {
    const out = compact([box('a', 0, 0, 6, 4), box('b', 6, 0, 6, 4), box('c', 0, 10, 6, 4)])
    expect(out.find((b) => b.id === 'c')!.y).toBe(4)
  })

  it('重叠块按 (y,x) 稳定排序后下推', () => {
    const out = compact([box('a', 0, 0, 12, 4), box('b', 0, 2, 12, 4)])
    expect(out.map((b) => b.id)).toEqual(['a', 'b'])
    expect(out[1].y).toBe(4)
  })

  it('幂等：再次压缩坐标不变', () => {
    const first = compact([box('a', 0, 0, 6, 4), box('b', 6, 5, 6, 4), box('c', 0, 9, 12, 3)])
    expect(compact(first)).toEqual(first)
  })

  it('不修改入参数组', () => {
    const input = [box('a', 0, 10, 12, 3)]
    compact(input)
    expect(input[0].y).toBe(10)
  })
})

describe('normalizeLayout', () => {
  it('先收敛越界再上浮', () => {
    const out = normalizeLayout([box('a', 20, 0, 20, 4), box('b', 0, 8, 12, 4)])
    expect(out).toEqual([box('a', 0, 0, 12, 4), box('b', 0, 4, 12, 4)])
  })
})

describe('collapseNarrow', () => {
  it('按 (y,x) 顺序排成单列，高度保留', () => {
    const out = collapseNarrow([box('b', 6, 0, 6, 3), box('a', 0, 0, 6, 4), box('c', 0, 4, 12, 2)])
    expect(out.map((b) => b.id)).toEqual(['a', 'b', 'c'])
    expect(out.map((b) => b.y)).toEqual([0, 4, 7])
    expect(out.every((b) => b.x === 0 && b.w === DASHBOARD_COLS)).toBe(true)
  })
})

describe('toGridStyle', () => {
  it('0-based 坐标映射为 1-based CSS Grid', () => {
    expect(toGridStyle(box('a', 2, 3, 4, 5))).toEqual({ gridColumn: '3 / span 4', gridRow: '4 / span 5' })
  })
})

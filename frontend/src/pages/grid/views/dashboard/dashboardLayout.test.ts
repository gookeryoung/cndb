/** dashboard 布局纯函数单元测试（ADR 0023 P0/P1：clamp / compact / 下推 / 预设 / 窄屏塌陷）. */
import { describe, expect, it } from 'vitest'
import {
  DASHBOARD_COLS, DASHBOARD_MAX_H, applyPreset, collapseNarrow, compact, findFreeSlot,
  moveBoxBy, normalizeLayout, resolveOverlap, resizeBoxBy, toGridStyle, clampBox,
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

describe('resolveOverlap', () => {
  it('移动块保持位置，重叠块被下推到其下方', () => {
    const out = resolveOverlap([
      box('a', 0, 0, 6, 4),
      box('b', 6, 0, 6, 4),
    ], 'a')
    // 先把 a 移动到 b 上方
    const moved = resolveOverlap([
      box('a', 6, 0, 6, 4),
      box('b', 6, 0, 6, 4),
    ], 'a')
    expect(moved.find((b) => b.id === 'a')!.y).toBe(0)
    expect(moved.find((b) => b.id === 'b')!.y).toBe(4)
    expect(out.find((b) => b.id === 'b')!.y).toBe(0)
  })

  it('无移动块时按 (y,x) 顺序解重叠', () => {
    const out = resolveOverlap([box('a', 0, 0, 12, 4), box('b', 0, 2, 12, 4)], null)
    expect(out.find((b) => b.id === 'b')!.y).toBe(4)
  })

  it('越界坐标先收敛', () => {
    const out = resolveOverlap([box('a', 20, 0, 20, 4)], 'a')
    expect(out[0]).toMatchObject({ x: 0, w: DASHBOARD_COLS })
  })
})

describe('normalizeLayout with moving id', () => {
  it('解重叠后再上浮消洞', () => {
    const out = normalizeLayout([
      box('a', 0, 0, 6, 4),
      box('b', 0, 0, 6, 4),
    ], DASHBOARD_COLS, 'a')
    expect(out.map((b) => b.id).sort()).toEqual(['a', 'b'])
    expect(out.find((b) => b.id === 'a')).toMatchObject({ y: 0 })
    expect(out.find((b) => b.id === 'b')).toMatchObject({ y: 4 })
  })
})

describe('findFreeSlot', () => {
  it('优先左上角空位', () => {
    expect(findFreeSlot([box('a', 0, 0, 6, 4)], 4, 4)).toEqual({ x: 6, y: 0 })
    expect(findFreeSlot([box('a', 0, 0, 12, 4)], 4, 4)).toEqual({ x: 0, y: 4 })
  })

  it('无空位时退化为纵坐标上限', () => {
    const full = Array.from({ length: 20 }, (_, i) => box(`a${i}`, 0, 0, 12, 1))
    // 每行都只占 1 格，仍能找到空位
    expect(findFreeSlot(full, 12, 1).y).toBeLessThanOrEqual(20)
  })
})

describe('moveBoxBy / resizeBoxBy', () => {
  it('平移按格数并收敛边界', () => {
    expect(moveBoxBy(box('a', 0, 0, 4, 4), -2, -1)).toMatchObject({ x: 0, y: 0 })
    expect(moveBoxBy(box('a', 8, 0, 4, 4), 10, 3)).toMatchObject({ x: 8, y: 3 })
  })

  it('缩放不越界且最小 1 格', () => {
    expect(resizeBoxBy(box('a', 0, 0, 4, 4), -9, -9)).toMatchObject({ w: 1, h: 1 })
    expect(resizeBoxBy(box('a', 0, 0, 4, 4), 20, 20)).toMatchObject({ w: DASHBOARD_COLS, h: DASHBOARD_MAX_H })
  })
})

describe('applyPreset', () => {
  const widgets = ['a', 'b', 'c', 'd', 'e'].map((id, i) => box(id, i % 2 === 0 ? 0 : 6, i < 2 ? 0 : 4, 6, 4))

  it('单栏：每块占满 12 列并纵向堆叠', () => {
    const out = applyPreset('single', widgets)
    expect(out.every((b) => b.w === 12 && b.x === 0)).toBe(true)
    expect(out.every((b, i) => i === 0 || b.y >= out[i - 1].y + out[i - 1].h)).toBe(true)
  })

  it('两栏等分：左右交替', () => {
    const out = applyPreset('two', widgets)
    expect(out.filter((b) => b.x === 0).length).toBe(3)
    expect(out.filter((b) => b.x === 6).length).toBe(2)
    expect(out.every((b) => b.w === 6)).toBe(true)
  })

  it('主次：8 + 4 交替', () => {
    const out = applyPreset('main-side', widgets)
    const widths = out.map((b) => b.w)
    expect(widths.filter((w) => w === 8).length).toBe(3)
    expect(widths.filter((w) => w === 4).length).toBe(2)
  })

  it('2×2：每块 6×6', () => {
    const out = applyPreset('grid-2x2', widgets)
    expect(out.every((b) => b.w === 6 && b.h === 6)).toBe(true)
  })

  it('KPI 条 + 图表：前四块 3×4 顶条，其余 6×8', () => {
    const out = applyPreset('kpi-charts', widgets)
    const top = out.filter((b) => b.y === 0)
    expect(top.length).toBe(4)
    expect(top.every((b) => b.w === 3 && b.h === 4)).toBe(true)
    const rest = out.filter((b) => b.y >= 4)
    expect(rest.every((b) => b.w === 6 && b.h === 8)).toBe(true)
  })

  it('只重排不丢块，输出无重叠', () => {
    const out = applyPreset('main-side', widgets)
    expect(out.map((b) => b.id).sort()).toEqual(widgets.map((b) => b.id).sort())
    for (let i = 0; i < out.length; i += 1) {
      for (let j = i + 1; j < out.length; j += 1) {
        const a = out[i]
        const b = out[j]
        const overlap = a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
        expect(overlap).toBe(false)
      }
    }
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

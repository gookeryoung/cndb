/** dashboard 12 列栅格布局纯函数（ADR 0023 P0）.
 *
 * P0 只实现只读渲染需要的 clamp / compact / 窄屏塌陷与 grid 样式映射；
 * 拖拽、重叠下推、预设与撤销栈在 P1 补齐。
 */

import type { CSSProperties } from 'react'

/** widget 在栅格中的整数坐标 */
export interface WidgetBox {
  id: string
  x: number
  y: number
  w: number
  h: number
}

/** 画布固定列数（ADR 0023 D3） */
export const DASHBOARD_COLS = 12
/** widget 高度上限（格） */
export const DASHBOARD_MAX_H = 20
/** widget 纵坐标上限 */
export const DASHBOARD_MAX_Y = 200

const int = (v: number): number => (Number.isFinite(v) ? Math.trunc(v) : 0)

/** 把单个 box 收敛到合法范围（I2 第一道防线） */
export function clampBox(box: WidgetBox, cols: number = DASHBOARD_COLS): WidgetBox {
  const safeCols = Math.max(1, int(cols))
  const w = Math.min(Math.max(1, int(box.w)), safeCols)
  const h = Math.min(Math.max(1, int(box.h)), DASHBOARD_MAX_H)
  const x = Math.min(Math.max(0, int(box.x)), safeCols - w)
  const y = Math.min(Math.max(0, int(box.y)), DASHBOARD_MAX_Y)
  return { ...box, x, y, w, h }
}

/** 两个 box 是否重叠（半开区间） */
function overlaps(a: WidgetBox, b: WidgetBox): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

/** 逐列上浮压缩：按 (y, x) 稳定排序，把每个 box 放到不与已放置块重叠的最小 y.
 *
 * 幂等：对已压缩结果再次调用不会改变坐标。
 */
export function compact(boxes: WidgetBox[]): WidgetBox[] {
  const placed: WidgetBox[] = []
  const sorted = [...boxes].sort((a, b) => a.y - b.y || a.x - b.x)
  for (const box of sorted) {
    let y = 0
    while (placed.some((p) => overlaps({ ...box, y }, p))) {
      const blocking = placed.filter((p) => overlaps({ ...box, y }, p))
      y = Math.max(...blocking.map((p) => p.y + p.h))
    }
    placed.push({ ...box, y })
  }
  return placed
}

/** 保存前唯一出口：先收敛越界，再上浮消洞（P0 无拖拽，不处理重叠下推） */
export function normalizeLayout(boxes: WidgetBox[], cols: number = DASHBOARD_COLS): WidgetBox[] {
  return compact(boxes.map((box) => clampBox(box, cols)))
}

/** 窄屏塌陷：按 (y, x) 顺序排成单列（w=cols、x=0，h 保留） */
export function collapseNarrow(boxes: WidgetBox[], cols: number = DASHBOARD_COLS): WidgetBox[] {
  let y = 0
  return [...boxes]
    .sort((a, b) => a.y - b.y || a.x - b.x)
    .map((box) => {
      const next = { ...box, x: 0, y, w: cols }
      y += box.h
      return next
    })
}

/** 生成 CSS Grid 定位样式（1-based 行/列） */
export function toGridStyle(box: WidgetBox): CSSProperties {
  return {
    gridColumn: `${box.x + 1} / span ${box.w}`,
    gridRow: `${box.y + 1} / span ${box.h}`,
  }
}

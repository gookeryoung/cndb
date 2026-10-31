/** dashboard 12 列栅格布局纯函数（ADR 0023 P0/P1）.
 *
 * P0：clamp / compact / 窄屏塌陷与 grid 样式映射；
 * P1：重叠下推、空位查找、5 种版式预设与拖拽/缩放位移收敛。
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

/**
 * 重叠下推：`movingId` 保持当前位置，其余块按 (y, x) 顺序被推到不重叠的最小 y.
 *
 * 拖动松手时使用；不做连锁动画，避免多块重排抖动（ADR 0023 §2）。
 */
export function resolveOverlap(
  boxes: WidgetBox[],
  movingId: string | null,
  cols: number = DASHBOARD_COLS,
): WidgetBox[] {
  const moving = boxes.find((b) => b.id === movingId)
  const rest = [...boxes]
    .filter((b) => b.id !== movingId)
    .sort((a, b) => a.y - b.y || a.x - b.x)
  const ordered = moving ? [moving, ...rest] : rest
  const placed: WidgetBox[] = []
  for (const box of ordered) {
    const candidate = clampBox(box, cols)
    let y = candidate.y
    let guard = 0
    while (placed.some((p) => overlaps({ ...candidate, y }, p)) && guard < 1000) {
      const blocking = placed.filter((p) => overlaps({ ...candidate, y }, p))
      y = Math.max(...blocking.map((p) => p.y + p.h))
      guard += 1
    }
    placed.push({ ...candidate, y })
  }
  const byId = new Map(placed.map((b) => [b.id, b]))
  return boxes.map((b) => byId.get(b.id) ?? clampBox(b, cols))
}

/** 保存前唯一出口：先收敛越界，再解重叠，最后上浮消洞 */
export function normalizeLayout(
  boxes: WidgetBox[],
  cols: number = DASHBOARD_COLS,
  movingId: string | null = null,
): WidgetBox[] {
  return compact(resolveOverlap(boxes.map((box) => clampBox(box, cols)), movingId, cols))
}

/** 找到第一个可放下 `w × h` 的空位（按行优先扫描） */
export function findFreeSlot(
  boxes: WidgetBox[],
  w: number,
  h: number,
  cols: number = DASHBOARD_COLS,
): { x: number; y: number } {
  const placed = boxes.map((b) => clampBox(b, cols))
  const width = Math.min(Math.max(1, int(w)), cols)
  const height = Math.min(Math.max(1, int(h)), DASHBOARD_MAX_H)
  for (let y = 0; y <= DASHBOARD_MAX_Y; y += 1) {
    for (let x = 0; x <= cols - width; x += 1) {
      const candidate: WidgetBox = { id: '__slot__', x, y, w: width, h: height }
      if (!placed.some((p) => overlaps(candidate, p))) return { x, y }
    }
  }
  return { x: 0, y: DASHBOARD_MAX_Y }
}

/** 把 box 平移指定格数并收敛越界 */
export function moveBoxBy(box: WidgetBox, dx: number, dy: number, cols: number = DASHBOARD_COLS): WidgetBox {
  return clampBox({ ...box, x: box.x + int(dx), y: box.y + int(dy) }, cols)
}

/** 把 box 按格数缩放并收敛越界（右下角手柄） */
export function resizeBoxBy(box: WidgetBox, dw: number, dh: number, cols: number = DASHBOARD_COLS): WidgetBox {
  return clampBox({ ...box, w: box.w + int(dw), h: box.h + int(dh) }, cols)
}

/** 版式预设标识（ADR 0023 §2 三通道之一） */
export type LayoutPresetKey = 'single' | 'two' | 'main-side' | 'grid-2x2' | 'kpi-charts'

export interface LayoutPreset {
  key: LayoutPresetKey
  label: string
}

export const DASHBOARD_PRESETS: LayoutPreset[] = [
  { key: 'single', label: '单栏' },
  { key: 'two', label: '两栏等分' },
  { key: 'main-side', label: '主次（8+4）' },
  { key: 'grid-2x2', label: '2×2' },
  { key: 'kpi-charts', label: 'KPI 条 + 图表' },
]

interface PresetSlot {
  x: number
  y: number
  w: number
  h: number
}

/** 按预设给第 i 个块生成槽位；超出预设槽位时按同列流式续排 */
function presetSlot(key: LayoutPresetKey, i: number, cols: number): PresetSlot {
  switch (key) {
    case 'single':
      return { x: 0, y: i * 6, w: cols, h: 6 }
    case 'two':
      return { x: (i % 2) * Math.floor(cols / 2), y: Math.floor(i / 2) * 6, w: Math.floor(cols / 2), h: 6 }
    case 'main-side': {
      const wide = Math.ceil(cols / 3) * 2
      const narrow = cols - wide
      const pair = Math.floor(i / 2)
      return i % 2 === 0
        ? { x: 0, y: pair * 6, w: wide, h: 6 }
        : { x: wide, y: pair * 6, w: narrow, h: 6 }
    }
    case 'grid-2x2':
      return { x: (i % 2) * Math.floor(cols / 2), y: Math.floor(i / 2) * 6, w: Math.floor(cols / 2), h: 6 }
    case 'kpi-charts': {
      if (i < 4) return { x: i * 3, y: 0, w: 3, h: 4 }
      const j = i - 4
      return { x: (j % 2) * Math.floor(cols / 2), y: 4 + Math.floor(j / 2) * 8, w: Math.floor(cols / 2), h: 8 }
    }
    default:
      return { x: 0, y: i * 6, w: cols, h: 6 }
  }
}

/**
 * 版式预设只重排现有块，不增删内容；数量不足留空位，多余按列流式续排.
 *
 * 输出经 `normalizeLayout` 收敛，便于直接写回 draft。
 */
export function applyPreset(
  preset: LayoutPresetKey,
  boxes: WidgetBox[],
  cols: number = DASHBOARD_COLS,
): WidgetBox[] {
  const ordered = [...boxes].sort((a, b) => a.y - b.y || a.x - b.x)
  const next = ordered.map((box, i) => {
    const slot = presetSlot(preset, i, cols)
    return clampBox({ ...box, ...slot }, cols)
  })
  return compact(next)
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

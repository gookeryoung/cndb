/** 甘特图时间轴纯函数模块 — 从 GanttView.tsx 抽出，可独立单元测试.
 *
 * 职责：
 * - 日期区间计算（daysBetween / computeTimeRange，前后各扩展 7/21 天）
 * - 双层时间轴分段构建（锚定层 + 细粒度层 + 语义锚点稀疏化）
 * - 缩放档位选择（8 档 ZOOM_LEVELS + 按 scale/视口自动选档）
 */

import type { RowResponse } from '@/api'

// ── 类型定义 ──────────────────────────────────────────

export interface GanttTask {
  row: RowResponse
  start: Date
  end: Date
  actualEnd?: Date | null
  title: string
  groupValue?: string
  color?: string
  progress: number
  assignee?: string
}

export type TimeScale = 'day' | 'week' | 'month' | 'quarter'

/** 时间轴分段 — 通用结构，双层 header 共用 */
export interface TimelineSegment {
  label: string
  date: Date
  width: number
  days: number
  left: number
  showLabel: boolean
}

/** 锚定粒度 */
export type AnchorScale = 'year' | 'month'

/** Zoom 档位定义 */
export interface ZoomLevel {
  name: string          // 显示文本，如 "月-日"
  pxPerDay: number      // 基准像素/天
  anchorScale: AnchorScale
  currentScale: TimeScale
  anchorLabel: string   // 上层 label 模板（直接字符串化锚定日期）
  currentLabel: string  // 下层 label 模板（直接字符串化当前刻度日期）
  /** 下层稀疏化的最小间距像素（锚定层不稀疏化，全部显示） */
  minGapPx: number
}

/** 8 档连续缩放 — 覆盖 quarter → day 的完整区间 */
export const ZOOM_LEVELS: ReadonlyArray<ZoomLevel> = [
  { name: '年-季度', pxPerDay: 1.5, anchorScale: 'year',  currentScale: 'quarter', anchorLabel: '${y}年',       currentLabel: 'Q${q}',          minGapPx: 0 },
  { name: '年-月',   pxPerDay: 4,   anchorScale: 'year',  currentScale: 'month',   anchorLabel: '${y}年',       currentLabel: '${m}月',         minGapPx: 0 },
  { name: '月-双周', pxPerDay: 7,   anchorScale: 'month', currentScale: 'week',    anchorLabel: '${y}年${m}月', currentLabel: '${m}/${d}',      minGapPx: 42 },
  { name: '月-周',   pxPerDay: 10,  anchorScale: 'month', currentScale: 'week',    anchorLabel: '${y}年${m}月', currentLabel: '${m}/${d}',      minGapPx: 48 },
  { name: '月-半周', pxPerDay: 14,  anchorScale: 'month', currentScale: 'day',     anchorLabel: '${y}年${m}月', currentLabel: '${m}/${d}',      minGapPx: 42 },
  { name: '月-日',   pxPerDay: 18,  anchorScale: 'month', currentScale: 'day',     anchorLabel: '${y}年${m}月', currentLabel: '${m}/${d}',      minGapPx: 36 },
  { name: '周-日',   pxPerDay: 26,  anchorScale: 'month', currentScale: 'day',     anchorLabel: '${y}年${m}月', currentLabel: '${m}/${d}',      minGapPx: 48 },
  { name: '日-细',   pxPerDay: 40,  anchorScale: 'month', currentScale: 'day',     anchorLabel: '${y}年${m}月', currentLabel: '${m}/${d}',      minGapPx: 56 },
] as const

// ── 时间轴计算 ────────────────────────────────────────

/** 计算两个日期之间的天数差（含当天） */
export function daysBetween(a: Date, b: Date): number {
  const diff = b.getTime() - a.getTime()
  return Math.max(1, Math.round(diff / (1000 * 60 * 60 * 24)) + 1)
}

/** 根据 tasks 计算时间轴范围（向前扩展 7 天、向后扩展 21 天，给锚定层留出完整锚点） */
export function computeTimeRange(tasks: GanttTask[]): { min: Date; max: Date } | null {
  if (tasks.length === 0) return null
  let min = tasks[0].start
  let max = tasks[0].end
  for (const t of tasks) {
    if (t.start < min) min = t.start
    if (t.end > max) max = t.end
  }
  const paddedMin = new Date(min)
  paddedMin.setDate(paddedMin.getDate() - 7)
  const paddedMax = new Date(max)
  paddedMax.setDate(paddedMax.getDate() + 21)
  return { min: paddedMin, max: paddedMax }
}

/** 用模板格式化日期 — 支持 ${y} ${m} ${d} ${q} */
export function fmtWithTemplate(template: string, d: Date): string {
  const y = d.getFullYear()
  const m = d.getMonth() + 1
  const day = d.getDate()
  const q = Math.floor(d.getMonth() / 3) + 1
  return template
    .split('${y}').join(String(y))
    .split('${m}').join(String(m))
    .split('${d}').join(String(day))
    .split('${q}').join(String(q))
}

/** 构建细粒度（current scale）分段 */
export function buildCurrentSegments(range: { min: Date; max: Date }, scale: TimeScale, pxPerDay: number, labelTemplate: string): TimelineSegment[] {
  const segments: TimelineSegment[] = []
  const totalDays = daysBetween(range.min, range.max)

  if (scale === 'day') {
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(range.min)
      d.setDate(d.getDate() + i)
      segments.push({
        label: fmtWithTemplate(labelTemplate, d),
        date: d,
        width: pxPerDay,
        days: 1,
        left: 0,
        showLabel: false, // 先全部 false，后续由锚定标记 + 稀疏化填充
      })
    }
  } else if (scale === 'week') {
    let cursor = new Date(range.min)
    while (cursor <= range.max) {
      const weekStart = new Date(cursor)
      weekStart.setDate(cursor.getDate() - cursor.getDay())
      const weekEnd = new Date(weekStart)
      weekEnd.setDate(weekStart.getDate() + 6)
      const days = daysBetween(weekStart, weekEnd)
      segments.push({
        label: fmtWithTemplate(labelTemplate, weekStart),
        date: weekStart,
        width: days * pxPerDay,
        days,
        left: 0,
        showLabel: false,
      })
      cursor = new Date(weekEnd)
      cursor.setDate(cursor.getDate() + 1)
    }
  } else if (scale === 'month') {
    let cursor = new Date(range.min.getFullYear(), range.min.getMonth(), 1)
    while (cursor <= range.max) {
      const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0)
      const days = daysBetween(
        cursor < range.min ? range.min : cursor,
        monthEnd > range.max ? range.max : monthEnd,
      )
      segments.push({
        label: fmtWithTemplate(labelTemplate, cursor),
        date: cursor,
        width: days * pxPerDay,
        days,
        left: 0,
        showLabel: true, // month 粒度本身就稀疏，全部显示
      })
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
    }
  } else { // quarter
    let cursor = new Date(range.min.getFullYear(), Math.floor(range.min.getMonth() / 3) * 3, 1)
    while (cursor <= range.max) {
      const qEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 3, 0)
      const days = daysBetween(
        cursor < range.min ? range.min : cursor,
        qEnd > range.max ? range.max : qEnd,
      )
      segments.push({
        label: fmtWithTemplate(labelTemplate, cursor),
        date: cursor,
        width: days * pxPerDay,
        days,
        left: 0,
        showLabel: true,
      })
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 3, 1)
    }
  }

  // 回填累积 left
  let acc = 0
  for (const seg of segments) {
    seg.left = acc
    acc += seg.width
  }
  return segments
}

/** 构建锚定层（anchor scale）分段 —— 永远完整显示（showLabel=true），不做稀疏化 */
export function buildAnchorSegments(range: { min: Date; max: Date }, anchorScale: AnchorScale, pxPerDay: number, labelTemplate: string): TimelineSegment[] {
  const segments: TimelineSegment[] = []

  if (anchorScale === 'year') {
    let cursor = new Date(range.min.getFullYear(), 0, 1)
    while (cursor <= range.max) {
      const yearEnd = new Date(cursor.getFullYear(), 11, 31)
      const days = daysBetween(
        cursor < range.min ? range.min : cursor,
        yearEnd > range.max ? range.max : yearEnd,
      )
      segments.push({
        label: fmtWithTemplate(labelTemplate, cursor),
        date: cursor,
        width: days * pxPerDay,
        days,
        left: 0,
        showLabel: true,
      })
      cursor = new Date(cursor.getFullYear() + 1, 0, 1)
    }
  } else { // month
    let cursor = new Date(range.min.getFullYear(), range.min.getMonth(), 1)
    while (cursor <= range.max) {
      const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0)
      const days = daysBetween(
        cursor < range.min ? range.min : cursor,
        monthEnd > range.max ? range.max : monthEnd,
      )
      segments.push({
        label: fmtWithTemplate(labelTemplate, cursor),
        date: cursor,
        width: days * pxPerDay,
        days,
        left: 0,
        showLabel: true,
      })
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
    }
  }

  let acc = 0
  for (const seg of segments) {
    seg.left = acc
    acc += seg.width
  }
  return segments
}

/** 标记下层 segments 的"语义锚点"（每月 1 号、每周一），作为稀疏化的保留点 */
export function markCurrentAnchors(segments: TimelineSegment[], scale: TimeScale): void {
  for (const seg of segments) {
    if (scale === 'day') {
      if (seg.date.getDate() === 1) seg.showLabel = true
    } else if (scale === 'week') {
      // week 刻度本身就是周一，全部都是锚点
      seg.showLabel = true
    }
    // month / quarter 已在 build 阶段全部 showLabel=true
  }
}

/** 下层稀疏化 —— 先保留语义锚点，再在锚点间均匀填充，保证间距 >= minGapPx */
export function sparseCurrentLabels(segments: TimelineSegment[], minGapPx: number): TimelineSegment[] {
  if (segments.length === 0 || minGapPx <= 0) {
    // minGapPx=0 表示全部显示（month/quarter 刻度）
    for (const seg of segments) seg.showLabel = true
    return segments
  }

  // 第一轮：保留语义锚点（已在上一步标记），去掉过近的锚点
  let lastShownLeft = -Infinity
  for (const seg of segments) {
    if (seg.showLabel) {
      if (seg.left - lastShownLeft < minGapPx) {
        seg.showLabel = false
      } else {
        lastShownLeft = seg.left
      }
    }
  }

  // 第二轮：在锚点之间的空位里均匀插入非锚点
  lastShownLeft = -Infinity
  for (const seg of segments) {
    if (seg.showLabel) {
      lastShownLeft = seg.left
      continue
    }
    const segCenter = seg.left + seg.width / 2
    if (segCenter - lastShownLeft >= minGapPx) {
      seg.showLabel = true
      lastShownLeft = segCenter
    }
  }

  return segments
}

/** 构建双层时间轴 —— 返回锚定层分段 + 下层分段 + 使用的档位 */
export function buildDualTimeline(
  range: { min: Date; max: Date },
  level: number,
): {
  anchorSegments: TimelineSegment[]
  currentSegments: TimelineSegment[]
  pxPerDay: number
  level: number
  levelDef: ZoomLevel
} {
  const lv = ZOOM_LEVELS[level] ?? ZOOM_LEVELS[2]
  const pxPerDay = lv.pxPerDay

  const anchorSegments = buildAnchorSegments(range, lv.anchorScale, pxPerDay, lv.anchorLabel)
  const currentSegments = buildCurrentSegments(range, lv.currentScale, pxPerDay, lv.currentLabel)

  // 锚定层永远 showLabel=true（在 buildAnchorSegments 已设）

  // 下层：先标记语义锚点 → 再稀疏化
  markCurrentAnchors(currentSegments, lv.currentScale)
  sparseCurrentLabels(currentSegments, lv.minGapPx)

  return { anchorSegments, currentSegments, pxPerDay, level, levelDef: lv }
}

/** 根据用户选定的 scale + 时间跨度，从 ZOOM_LEVELS 中选出最合适的档位.
 *  策略：优先匹配 currentScale，再选 pxPerDay 使总宽度落在 [600, 3000] 区间。 */
export function selectZoomLevelForScale(scale: TimeScale, totalDays: number): number {
  const candidates = ZOOM_LEVELS
    .map((lv, i) => ({ lv, i }))
    .filter(x => x.lv.currentScale === scale)

  if (candidates.length === 0) return 2 // fallback

  // 计算期望总宽度
  const totalDaysNum = totalDays
  // 找最合适的档位：总宽度落在 [600, 3000] 内的第一个，否则取中间
  let best = candidates[Math.floor(candidates.length / 2)]
  let bestScore = Infinity
  for (const c of candidates) {
    const w = totalDaysNum * c.lv.pxPerDay
    // 评分：落在区间内得 0 分，偏离量越小越好
    const score = w < 600 ? 600 - w : w > 3000 ? w - 3000 : 0
    if (score < bestScore) {
      bestScore = score
      best = c
    }
  }
  return best.i
}

/** 根据视口宽度和时间跨度做二次缩放 —— 如果默认档位产生的总宽度偏离太远则微调 level.
 *  这个函数返回调整后的 level（不直接改 pxPerDay，保持档位离散）。 */
export function autoAdjustLevel(
  level: number,
  totalDays: number,
  viewportWidth: number,
): number {
  const targetMinPx = viewportWidth * 0.6
  const targetMaxPx = viewportWidth * 2
  let lv = level
  let safety = 0
  while (safety < ZOOM_LEVELS.length) {
    const w = totalDays * ZOOM_LEVELS[lv].pxPerDay
    if (w >= targetMinPx && w <= targetMaxPx) break
    if (w < targetMinPx) {
      if (lv < ZOOM_LEVELS.length - 1) lv++
      else break
    } else {
      if (lv > 0) lv--
      else break
    }
    safety++
  }
  return lv
}

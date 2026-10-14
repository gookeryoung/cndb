/** 日历视图工具：日期网格、事件构建、密度样式与跨视图事件工具. */

import type { Field, RowResponse } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { formatFieldDisplayValue, getLinkFirstLabel, getMultiSelectFirstLabel } from '../../cells/fieldValueFormat'
import { fmtDate, parseDate } from '../../cells/dateUtils'
import { isDoneRow } from '../kanbanBoard'
import type { DoneCtx } from '../kanbanBoard'
import { groupColor } from '@/utils/paletteColor'
import { CalendarEvent, DensityStyle } from './calendarTypes'

// ── 工具函数（日期已抽到 ../cells/dateUtils.ts） ───────────────

/** 获取某月的日历网格（6 行 x 7 列，周日起始） */
export function getMonthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1)
  const startDay = first.getDay() // 0=周日
  const start = new Date(year, month, 1 - startDay)
  const grid: Date[] = []
  for (let i = 0; i < 42; i++) {
    grid.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
  }
  return grid
}

/** 获取某年的 12 个月起始日 */
export function getYearMonths(year: number): Date[] {
  return Array.from({ length: 12 }, (_, m) => new Date(year, m, 1))
}

/** 获取某周的 7 天（周日起始） */
export function getWeekDays(base: Date): Date[] {
  const day = base.getDay()
  const start = new Date(base.getFullYear(), base.getMonth(), base.getDate() - day)
  return Array.from({ length: 7 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
}

/** 计算当月有事件的日期集合（用 Set 加速查找） */
export function getEventDates(events: CalendarEvent[]): Set<string> {
  const set = new Set<string>()
  for (const ev of events) {
    set.add(fmtDate(ev.date))
  }
  return set
}

// ── 事件构建 ──────────────────────────────────────────

/** 将原始 rows 转成 CalendarEvent 列表（doneCtx 用于完成标志判定，与看板一致） */
export function buildEvents(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
  doneCtx: DoneCtx | null,
): CalendarEvent[] {
  const startField = opts.start_field as string | undefined
  const titleField = opts.title_field as string | undefined
  const groupField = opts.group_field as string | undefined

  if (!startField) return []

  // 字段名 -> Field 映射，用于格式化 link/select 等复杂类型
  const fieldMap = new Map<string, Field>(fields.map((f) => [f.name, f]))
  const fmtTitle = (name: string | undefined, raw: unknown, fallback: string): string => {
    if (!name) return fallback
    const fd = fieldMap.get(name)
    if (!fd) return raw != null ? String(raw) : fallback
    return formatFieldDisplayValue(fd, raw) || fallback
  }
  const fmtGroup = (name: string, raw: unknown): string | undefined => {
    const fd = fieldMap.get(name)
    if (!fd) return raw != null && raw !== '' ? String(raw) : undefined
    if (fd.field_type === 'link') return getLinkFirstLabel(raw) || undefined
    if (fd.field_type === 'multi_select' || fd.field_type === 'multiselect') return getMultiSelectFirstLabel(raw) || undefined
    const s = formatFieldDisplayValue(fd, raw)
    return s || undefined
  }

  const events: CalendarEvent[] = []
  for (const row of rows) {
    const date = parseDate(row[startField])
    if (!date) continue

    // 标题：优先 title_field，否则第一个 text 字段，否则 #id
    let title = String(row.id)
    if (titleField) {
      title = fmtTitle(titleField, row[titleField], String(row.id))
    } else {
      const textFld = fields.find((f) => f.field_type === 'text')
      if (textFld) title = fmtTitle(textFld.name, row[textFld.name], String(row.id))
    }

    // 分组/颜色
    let groupValue: string | undefined
    let color: string | undefined
    if (groupField) {
      groupValue = fmtGroup(groupField, row[groupField])
      if (groupValue) color = groupColor(groupValue)
    }

    events.push({ row, date, title, groupValue, color, isDone: isDoneRow(row, doneCtx) })
  }
  return events
}

// ── 密度样式 ──────────────────────────────────────────

export function densityStyle(density: Density): DensityStyle {
  if (density === 'compact') {
    return { navPadding: 6, navFontSize: 12, cellFontSize: 11, eventFontSize: 11, eventPadding: '1px 4px', eventRadius: 3, dayCellMinHeight: 80, monthCellHeight: 70, yearCellHeight: 60 }
  }
  if (density === 'spacious') {
    return { navPadding: 12, navFontSize: 14, cellFontSize: 14, eventFontSize: 13, eventPadding: '4px 10px', eventRadius: 6, dayCellMinHeight: 140, monthCellHeight: 110, yearCellHeight: 96 }
  }
  return { navPadding: 8, navFontSize: 13, cellFontSize: 13, eventFontSize: 12, eventPadding: '2px 6px', eventRadius: 4, dayCellMinHeight: 100, monthCellHeight: 90, yearCellHeight: 80 }
}

// ── 跨视图共用的事件工具 ──────────────────────────────

/** 把事件按日期字符串分组（MonthView / WeekView 共用）.
 *  filterDays 可选：只保留这些日期范围内的事件（WeekView 过滤本周用）。
 */
export function groupEventsByDay(events: CalendarEvent[], filterDays?: Date[]): Map<string, CalendarEvent[]> {
  const map = new Map<string, CalendarEvent[]>()
  const allowed = filterDays ? new Set(filterDays.map(d => fmtDate(d))) : null
  for (const ev of events) {
    const key = fmtDate(ev.date)
    if (allowed && !allowed.has(key)) continue
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(ev)
  }
  return map
}

/** 构造事件 badge 的统一 style 对象（MonthView / WeekView 共用）.
 *  已完成事件与看板一致：绿色左边框 + 主题绿底 + 文字删除线置灰。
 */
export function eventBadgeStyle(event: CalendarEvent, ds: DensityStyle, lineHeight = 1.3): React.CSSProperties {
  if (event.isDone) {
    return {
      fontSize: ds.eventFontSize,
      padding: ds.eventPadding,
      borderRadius: ds.eventRadius,
      background: 'var(--cn-bg-success-subtle)',
      color: 'var(--cn-text-muted)',
      cursor: 'pointer',
      borderLeft: '3px solid #52c41a',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      lineHeight,
      textDecoration: 'line-through',
    }
  }
  return {
    fontSize: ds.eventFontSize,
    padding: ds.eventPadding,
    borderRadius: ds.eventRadius,
    background: event.color ? `${event.color}20` : 'var(--cn-bg-muted)',
    color: event.color || 'var(--cn-brand-color)',
    cursor: 'pointer',
    borderLeft: `3px solid ${event.color || 'var(--cn-brand-color)'}`,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    lineHeight,
  }
}

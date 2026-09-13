/** 日历视图组件 — 支持年/月/周三层级的万年历模式.
 *
 * view_options 配置字段：
 * - start_field:    起始日期字段（date/datetime，必填）
 * - end_field:      结束日期字段（可选，用于渲染跨天事件）
 * - title_field:    事件标题字段（可选，留空用主键或第一个文本字段）
 * - group_field:    分组/颜色字段（select，可选，不同值渲染不同侧边色条）
 * - calendar_mode:  默认打开的日历层级 'year' | 'month' | 'week'（默认 'month'）
 * - show_weekend:   是否高亮周末（默认 true）
 */

import { useMemo, useState } from 'react'
import { Button, Segmented, Space, Tooltip, Empty, Tag } from 'antd'
import {
  LeftOutlined,
  RightOutlined,
  CalendarOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'

// ── 类型定义 ──────────────────────────────────────────

type CalendarMode = 'year' | 'month' | 'week'

interface CalendarViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

interface CalendarEvent {
  row: RowResponse
  start: Date
  end: Date
  title: string
  groupValue?: string
  color?: string
}

// ── 工具函数 ──────────────────────────────────────────

/** 解析日期字符串为 Date（只取日期部分） */
function parseDateOnly(value: unknown): Date | null {
  if (!value) return null
  const str = String(value).slice(0, 10)
  const d = new Date(str + 'T00:00:00')
  return Number.isNaN(d.getTime()) ? null : d
}

/** 格式化日期为 YYYY-MM-DD */
function fmtDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 获取某月的日历网格（6 行 x 7 列，周日起始） */
function getMonthGrid(year: number, month: number): Date[] {
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
function getYearMonths(year: number): Date[] {
  return Array.from({ length: 12 }, (_, m) => new Date(year, m, 1))
}

/** 获取某周的 7 天（周日起始） */
function getWeekDays(base: Date): Date[] {
  const day = base.getDay()
  const start = new Date(base.getFullYear(), base.getMonth(), base.getDate() - day)
  return Array.from({ length: 7 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
}

/** 计算当月有事件的日期集合（用 Set 加速查找） */
function getEventDates(events: CalendarEvent[]): Set<string> {
  const set = new Set<string>()
  for (const ev of events) {
    const s = new Date(ev.start.getFullYear(), ev.start.getMonth(), ev.start.getDate())
    const e = new Date(ev.end.getFullYear(), ev.end.getMonth(), ev.end.getDate())
    for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
      set.add(fmtDate(d))
    }
  }
  return set
}

/** 预设色板（给 group_field 自动配色） */
const GROUP_PALETTE = [
  '#1677ff', '#f5222d', '#fa8c16', '#52c41a', '#722ed1',
  '#eb2f96', '#13c2c2', '#faad14', '#2f54eb', '#a0d911',
]

/** 给分组值分配稳定颜色（基于字符串 hash） */
function groupColor(value: string): string {
  let h = 0
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) & 0x7fffffff
  return GROUP_PALETTE[h % GROUP_PALETTE.length]
}

// ── 事件构建 ──────────────────────────────────────────

/** 将原始 rows 转成 CalendarEvent 列表 */
function buildEvents(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
): CalendarEvent[] {
  const startField = opts.start_field as string | undefined
  const endField = opts.end_field as string | undefined
  const titleField = opts.title_field as string | undefined
  const groupField = opts.group_field as string | undefined

  if (!startField) return []

  // 查找字段定义（用于格式化 link/select 等复杂类型）
  const findField = (name: string): Field | undefined => fields.find((f) => f.name === name)

  const events: CalendarEvent[] = []
  for (const row of rows) {
    const start = parseDateOnly(row[startField])
    if (!start) continue

    // 结束日期：end_field 有值且晚于 start 则用之，否则单天事件
    let end = start
    if (endField) {
      const rawEnd = parseDateOnly(row[endField])
      if (rawEnd && rawEnd.getTime() >= start.getTime()) end = rawEnd
    }

    // 标题：优先 title_field，否则第一个 text 字段，否则主键
    let title = String(row.id)
    if (titleField) {
      const f = findField(titleField)
      title = f ? String(row[titleField] ?? row.id) : String(row[titleField] ?? row.id)
    } else {
      const textFld = fields.find((f) => f.field_type === 'text')
      if (textFld) title = String(row[textFld.name] ?? row.id)
      else {
        const primaryFld = fields.find((f) => f.is_primary)
        if (primaryFld) title = String(row[primaryFld.name] ?? row.id)
      }
    }

    // 分组/颜色
    let groupValue: string | undefined
    let color: string | undefined
    if (groupField) {
      const raw = row[groupField]
      groupValue = raw != null && raw !== '' ? String(raw) : undefined
      if (groupValue) color = groupColor(groupValue)
    }

    events.push({ row, start, end, title, groupValue, color })
  }
  return events
}

// ── 密度样式 ──────────────────────────────────────────

interface DensityStyle {
  navPadding: number
  navFontSize: number
  cellFontSize: number
  eventFontSize: number
  eventPadding: string
  eventRadius: number
  dayCellMinHeight: number
  monthCellHeight: number
  yearCellHeight: number
}

function densityStyle(density: Density): DensityStyle {
  if (density === 'compact') {
    return { navPadding: 6, navFontSize: 12, cellFontSize: 11, eventFontSize: 11, eventPadding: '1px 4px', eventRadius: 3, dayCellMinHeight: 80, monthCellHeight: 70, yearCellHeight: 60 }
  }
  if (density === 'spacious') {
    return { navPadding: 12, navFontSize: 14, cellFontSize: 14, eventFontSize: 13, eventPadding: '4px 10px', eventRadius: 6, dayCellMinHeight: 140, monthCellHeight: 110, yearCellHeight: 96 }
  }
  return { navPadding: 8, navFontSize: 13, cellFontSize: 13, eventFontSize: 12, eventPadding: '2px 6px', eventRadius: 4, dayCellMinHeight: 100, monthCellHeight: 90, yearCellHeight: 80 }
}

// ── 年视图 YearView ──────────────────────────────────

function YearView({
  year,
  events,
  density,
  onSelectMonth,
  onEventClick,
}: {
  year: number
  events: CalendarEvent[]
  density: Density
  onSelectMonth: (month: number) => void
  onEventClick?: (r: RowResponse) => void
}) {
  const ds = densityStyle(density)
  const months = getYearMonths(year)
  const today = new Date()
  const todayStr = fmtDate(today)

  return (
    <div style={{ padding: ds.navPadding }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: ds.navPadding,
        }}
      >
        {months.map((_m, idx) => {
          const mEvents = events.filter((ev) => ev.start.getMonth() === idx || ev.end.getMonth() === idx)
          const eventDates = getEventDates(mEvents)
          const isCurrentMonth = today.getFullYear() === year && today.getMonth() === idx

          return (
            <div
              key={idx}
              onClick={() => onSelectMonth(idx)}
              style={{
                border: `1px solid ${isCurrentMonth ? '#1677ff' : '#e5e7eb'}`,
                borderRadius: ds.eventRadius + 2,
                padding: ds.navPadding,
                background: isCurrentMonth ? '#f0f5ff' : '#fff',
                cursor: 'pointer',
                minHeight: ds.yearCellHeight,
                transition: 'box-shadow 0.15s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.boxShadow = '0 2px 6px rgba(0,0,0,0.08)')}
              onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'none')}
            >
              {/* 月份标题 */}
              <div
                style={{
                  fontWeight: 600,
                  fontSize: ds.cellFontSize,
                  color: isCurrentMonth ? '#1677ff' : '#1f2937',
                  marginBottom: 4,
                  textAlign: 'center',
                }}
              >
                {idx + 1}月
              </div>

              {/* 迷你日历网格（7 列） */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 1, fontSize: ds.cellFontSize - 4 }}>
                {['日', '一', '二', '三', '四', '五', '六'].map((d) => (
                  <div key={d} style={{ textAlign: 'center', color: '#9ca3af' }}>{d}</div>
                ))}
                {getMonthGrid(year, idx).map((d) => {
                  const isCurrentMonthCell = d.getMonth() === idx
                  const dateStr = fmtDate(d)
                  const hasEvent = eventDates.has(dateStr)
                  const isToday = dateStr === todayStr
                  return (
                    <div
                      key={dateStr}
                      style={{
                        textAlign: 'center',
                        lineHeight: `${ds.cellFontSize - 2}px`,
                        color: !isCurrentMonthCell ? '#e5e7eb' : '#374151',
                        position: 'relative',
                      }}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (hasEvent) {
                          const ev = mEvents.find((ev) => fmtDate(ev.start) === dateStr)
                          if (ev) onEventClick?.(ev.row)
                        }
                      }}
                    >
                      {isToday && isCurrentMonthCell ? (
                        <span style={{ background: '#1677ff', color: '#fff', borderRadius: '50%', padding: '0 2px' }}>{d.getDate()}</span>
                      ) : (
                        d.getDate()
                      )}
                      {hasEvent && isCurrentMonthCell && (
                        <span style={{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)', width: 4, height: 4, background: '#1677ff', borderRadius: '50%' }} />
                      )}
                    </div>
                  )
                })}
              </div>

              {/* 事件数量 */}
              {mEvents.length > 0 && (
                <div style={{ marginTop: 4, textAlign: 'center', fontSize: ds.cellFontSize - 4, color: '#1677ff' }}>
                  {mEvents.length} 条
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 月视图 MonthView ──────────────────────────────────

function MonthView({
  year,
  month,
  events,
  density,
  onDayClick,
  onEventClick,
}: {
  year: number
  month: number
  events: CalendarEvent[]
  density: Density
  onDayClick?: (date: Date) => void
  onEventClick?: (r: RowResponse) => void
}) {
  const ds = densityStyle(density)
  const grid = getMonthGrid(year, month)
  const today = new Date()
  const todayStr = fmtDate(today)

  // 预计算每天的事件
  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const ev of events) {
      const s = new Date(ev.start.getFullYear(), ev.start.getMonth(), ev.start.getDate())
      const e = new Date(ev.end.getFullYear(), ev.end.getMonth(), ev.end.getDate())
      for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
        const key = fmtDate(d)
        if (!map.has(key)) map.set(key, [])
        map.get(key)!.push(ev)
      }
    }
    return map
  }, [events])

  // 计算事件跨天信息（同一天内只渲染"头部"，其余天渲染小标记）
  const getEventDisplay = (ev: CalendarEvent, dayStr: string): { showFull: boolean; isStart: boolean; spanDays: number } => {
    const sStr = fmtDate(ev.start)
    const isStart = dayStr === sStr
    const spanDays = Math.max(1, Math.round((ev.end.getTime() - ev.start.getTime()) / (1000 * 60 * 60 * 24)) + 1)
    void ev.end // 预留 eStr 计算
    return { showFull: isStart, isStart, spanDays }
  }

  const WEEK_HEADERS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

  return (
    <div style={{ padding: ds.navPadding }}>
      {/* 周标题行 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: 1,
          marginBottom: 2,
        }}
      >
        {WEEK_HEADERS.map((h, idx) => (
          <div
            key={h}
            style={{
              textAlign: 'center',
              fontWeight: 600,
              fontSize: ds.cellFontSize,
              padding: '4px 0',
              color: idx === 0 || idx === 6 ? '#ff4d4f' : '#374151',
            }}
          >
            {h}
          </div>
        ))}
      </div>

      {/* 日历网格 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: 1,
          border: '1px solid #e5e7eb',
          borderRadius: ds.eventRadius + 2,
          overflow: 'hidden',
          background: '#e5e7eb',
        }}
      >
        {grid.map((d) => {
          const dateStr = fmtDate(d)
          const isCurrentMonth = d.getMonth() === month
          const isWeekend = d.getDay() === 0 || d.getDay() === 6
          const isToday = dateStr === todayStr
          const dayEvents = eventsByDay.get(dateStr) || []

          // 去重（跨天事件在同一天内可能重复）
          const uniqueEvents = Array.from(new Set(dayEvents))

          return (
            <div
              key={dateStr}
              onClick={() => onDayClick?.(d)}
              style={{
                minHeight: ds.dayCellMinHeight,
                background: isCurrentMonth ? (isWeekend ? '#fafafa' : '#fff') : '#f9fafb',
                padding: 4,
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
                border: 'none',
                position: 'relative',
              }}
            >
              {/* 日期数字 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {isToday ? (
                  <span
                    style={{
                      background: '#1677ff',
                      color: '#fff',
                      borderRadius: '50%',
                      width: ds.cellFontSize + 8,
                      height: ds.cellFontSize + 8,
                      lineHeight: `${ds.cellFontSize + 8}px`,
                      textAlign: 'center',
                      fontSize: ds.cellFontSize,
                    }}
                  >
                    {d.getDate()}
                  </span>
                ) : (
                  <span
                    style={{
                      fontSize: ds.cellFontSize,
                      color: !isCurrentMonth ? '#d1d5db' : (isWeekend ? '#ff4d4f' : '#374151'),
                    }}
                  >
                    {d.getDate()}
                  </span>
                )}
                {uniqueEvents.length > 3 && isCurrentMonth && (
                  <span style={{ fontSize: ds.cellFontSize - 4, color: '#9ca3af' }}>+{uniqueEvents.length - 3}</span>
                )}
              </div>

              {/* 事件列表 */}
              <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 1 }}>
                {uniqueEvents.slice(0, 3).map((ev, idx) => {
                  const display = getEventDisplay(ev, dateStr)
                  if (!display.showFull) {
                    // 跨天的后续日期 — 只显示小色条
                    return (
                      <div
                        key={`${ev.row.id}-${idx}`}
                        onClick={(e) => { e.stopPropagation(); onEventClick?.(ev.row) }}
                        style={{
                          height: 4,
                          borderRadius: 2,
                          background: ev.color || '#1677ff',
                          cursor: 'pointer',
                          opacity: 0.6,
                        }}
                        title={ev.title}
                      />
                    )
                  }
                  return (
                    <div
                      key={`${ev.row.id}-${idx}`}
                      onClick={(e) => { e.stopPropagation(); onEventClick?.(ev.row) }}
                      style={{
                        fontSize: ds.eventFontSize,
                        padding: ds.eventPadding,
                        borderRadius: ds.eventRadius,
                        background: ev.color ? `${ev.color}15` : '#e6f4ff',
                        color: ev.color || '#1677ff',
                        cursor: 'pointer',
                        borderLeft: `3px solid ${ev.color || '#1677ff'}`,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        lineHeight: 1.3,
                      }}
                      title={ev.title}
                    >
                      {ev.title}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 周视图 WeekView ──────────────────────────────────

function WeekView({
  baseDate,
  events,
  density,
  onEventClick,
}: {
  baseDate: Date
  events: CalendarEvent[]
  density: Density
  onEventClick?: (r: RowResponse) => void
}) {
  const ds = densityStyle(density)
  const weekDays = getWeekDays(baseDate)
  const today = new Date()
  const todayStr = fmtDate(today)

  const DAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

  // 按天分组事件
  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const ev of events) {
      const s = new Date(ev.start.getFullYear(), ev.start.getMonth(), ev.start.getDate())
      const e = new Date(ev.end.getFullYear(), ev.end.getMonth(), ev.end.getDate())
      for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
        // 只保留本周范围内的
        const dStr = fmtDate(d)
        if (!weekDays.some((wd) => fmtDate(wd) === dStr)) continue
        if (!map.has(dStr)) map.set(dStr, [])
        map.get(dStr)!.push(ev)
      }
    }
    return map
  }, [events, weekDays])

  const weekStart = fmtDate(weekDays[0])
  const weekEnd = fmtDate(weekDays[6])

  return (
    <div style={{ padding: ds.navPadding }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: ds.navPadding,
        }}
      >
        {weekDays.map((d, idx) => {
          const dateStr = fmtDate(d)
          const dayEvents = eventsByDay.get(dateStr) || []
          const uniqueEvents = Array.from(new Set(dayEvents))
          const isWeekend = d.getDay() === 0 || d.getDay() === 6
          const isToday = dateStr === todayStr

          return (
            <div
              key={dateStr}
              style={{
                border: '1px solid #e5e7eb',
                borderRadius: ds.eventRadius + 2,
                background: isWeekend ? '#fafafa' : '#fff',
                overflow: 'hidden',
              }}
            >
              {/* 日期头 */}
              <div
                style={{
                  padding: `${ds.navPadding}px 8px`,
                  borderBottom: '1px solid #e5e7eb',
                  background: isToday ? '#1677ff' : (isWeekend ? '#f5f5f5' : '#fafafa'),
                  color: isToday ? '#fff' : (isWeekend ? '#ff4d4f' : '#374151'),
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: ds.cellFontSize - 2, opacity: isToday ? 0.9 : 0.7 }}>
                  {DAY_LABELS[idx]}
                </div>
                <div style={{ fontWeight: 600, fontSize: ds.cellFontSize + 2 }}>
                  {d.getMonth() + 1}/{d.getDate()}
                </div>
              </div>

              {/* 事件列表 */}
              <div style={{ padding: ds.navPadding, minHeight: ds.dayCellMinHeight, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {uniqueEvents.length === 0 ? (
                  <div style={{ color: '#d1d5db', textAlign: 'center', fontSize: ds.eventFontSize - 1, padding: `${ds.navPadding + 4}px 0` }}>
                    无
                  </div>
                ) : (
                  uniqueEvents.map((ev, i) => (
                    <div
                      key={`${ev.row.id}-${i}`}
                      onClick={() => onEventClick?.(ev.row)}
                      style={{
                        fontSize: ds.eventFontSize,
                        padding: ds.eventPadding,
                        borderRadius: ds.eventRadius,
                        background: ev.color ? `${ev.color}15` : '#e6f4ff',
                        color: ev.color || '#1677ff',
                        cursor: 'pointer',
                        borderLeft: `3px solid ${ev.color || '#1677ff'}`,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        lineHeight: 1.4,
                      }}
                      title={ev.title}
                    >
                      {ev.title}
                      {ev.groupValue && (
                        <Tag color={ev.color} style={{ marginLeft: 4, fontSize: ds.eventFontSize - 2, padding: '0 4px' }}>
                          {ev.groupValue}
                        </Tag>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ textAlign: 'center', marginTop: 8, fontSize: ds.cellFontSize - 2, color: '#9ca3af' }}>
        本周范围：{weekStart} ~ {weekEnd}
      </div>
    </div>
  )
}

// ── 主组件 CalendarView ──────────────────────────────

export default function CalendarView({ rows, fields, view, density, onRowClick }: CalendarViewProps) {
  // 稳定的 view_options 引用 — 避免每次渲染创建新对象导致 useMemo 重新计算
  const opts = useMemo(
    () => (view?.view_options || {}) as Record<string, unknown>,
    [view?.view_options],
  )

  // 当前"注视日期"——所有层级导航围绕此日期展开
  const [focusDate, setFocusDate] = useState<Date>(() => new Date())
  const [mode, setMode] = useState<CalendarMode>(() => (opts.calendar_mode as CalendarMode) || 'month')

  // 从 options 中解析 show_weekend 等偏好（留作未来扩展）
  void opts.show_weekend

  const year = focusDate.getFullYear()
  const month = focusDate.getMonth()

  // 构建事件列表
  const events = useMemo(() => buildEvents(rows, fields, opts), [rows, fields, opts])

  // 标题栏文本（必须在条件 return 之前声明）
  const titleText = useMemo(() => {
    if (mode === 'year') return `${year} 年`
    if (mode === 'month') return `${year} 年 ${month + 1} 月`
    const wd = getWeekDays(focusDate)
    return `${fmtDate(wd[0])} ~ ${fmtDate(wd[6])}`
  }, [mode, year, month, focusDate])

  const ds = densityStyle(density)

  // 导航函数
  const goPrev = () => {
    const d = new Date(focusDate)
    if (mode === 'year') d.setFullYear(d.getFullYear() - 1)
    else if (mode === 'month') d.setMonth(d.getMonth() - 1)
    else d.setDate(d.getDate() - 7)
    setFocusDate(d)
  }

  const goNext = () => {
    const d = new Date(focusDate)
    if (mode === 'year') d.setFullYear(d.getFullYear() + 1)
    else if (mode === 'month') d.setMonth(d.getMonth() + 1)
    else d.setDate(d.getDate() + 7)
    setFocusDate(d)
  }

  const goToday = () => setFocusDate(new Date())

  if (events.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty
          description={
            opts.start_field
              ? '当前时间范围内没有事件'
              : '日历视图需要配置 start_field（起始日期字段）'
          }
          style={{ padding: 48 }}
        />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 导航工具栏 */}
      <div
        style={{
          padding: `${ds.navPadding}px ${ds.navPadding + 4}px`,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          borderBottom: '1px solid #f0f0f0',
          background: '#fff',
        }}
      >
        {/* 模式切换 */}
        <Segmented
          size="small"
          value={mode}
          onChange={(v) => setMode(v as CalendarMode)}
          options={[
            { value: 'year', label: '年' },
            { value: 'month', label: '月' },
            { value: 'week', label: '周' },
          ]}
        />

        {/* 标题 */}
        <div style={{ fontWeight: 600, fontSize: ds.navFontSize + 2, marginLeft: 8, minWidth: 160 }}>
          <CalendarOutlined style={{ marginRight: 6, color: '#1677ff' }} />
          {titleText}
        </div>

        {/* 前进/后退 */}
        <Space.Compact size="small">
          <Tooltip title="上一周期">
            <Button icon={<LeftOutlined />} onClick={goPrev} />
          </Tooltip>
          <Tooltip title="回到今天">
            <Button icon={<ReloadOutlined />} onClick={goToday}>今天</Button>
          </Tooltip>
          <Tooltip title="下一周期">
            <Button icon={<RightOutlined />} onClick={goNext} />
          </Tooltip>
        </Space.Compact>

        {/* 事件数量 */}
        <div style={{ marginLeft: 'auto', fontSize: ds.navFontSize, color: '#9ca3af' }}>
          共 {events.length} 个事件
        </div>
      </div>

      {/* 日历主体 */}
      <div style={{ flex: 1, overflow: 'auto', background: '#fff' }}>
        {mode === 'year' && (
          <YearView
            year={year}
            events={events}
            density={density}
            onSelectMonth={(m) => {
              setFocusDate(new Date(year, m, 1))
              setMode('month')
            }}
            onEventClick={onRowClick}
          />
        )}
        {mode === 'month' && (
          <MonthView
            year={year}
            month={month}
            events={events}
            density={density}
            onDayClick={(d) => setFocusDate(d)}
            onEventClick={onRowClick}
          />
        )}
        {mode === 'week' && (
          <WeekView
            baseDate={focusDate}
            events={events}
            density={density}
            onEventClick={onRowClick}
          />
        )}
      </div>
    </div>
  )
}

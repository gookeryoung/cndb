/** 日历视图组件 — 支持年/月/周三层级的万年历模式.
 *
 * view_options 配置字段：
 * - start_field:    事件日期字段（date/datetime，必填）
 * - title_field:    事件标题字段（可选，留空用主键或第一个文本字段）
 * - group_field:    分组/颜色字段（select，可选，不同值渲染不同侧边色条）
 * - calendar_mode:  默认打开的日历层级 'year' | 'month' | 'week'（默认 'month'）
 * - show_weekend:   是否高亮周末（默认 true）
 *
 * 注：日历视图只支持单点日期事件，不渲染跨天持续标识。进度跟踪请使用其他视图。
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
import { formatFieldDisplayValue, getLinkFirstLabel, getMultiSelectFirstLabel } from './fieldValueFormat'
import { parseDate, fmtDate } from './dateUtils'
import { resolveOpts, CALENDAR_OPTIONS } from './viewOptionSchema'

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
  date: Date
  title: string
  groupValue?: string
  color?: string
}

// ── 工具函数（日期已抽到 ./dateUtils.ts） ───────────────

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
    set.add(fmtDate(ev.date))
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

    // 标题：优先 title_field，否则第一个 text 字段，否则主键
    let title = String(row.id)
    if (titleField) {
      title = fmtTitle(titleField, row[titleField], String(row.id))
    } else {
      const textFld = fields.find((f) => f.field_type === 'text')
      if (textFld) title = fmtTitle(textFld.name, row[textFld.name], String(row.id))
      else {
        const primaryFld = fields.find((f) => f.is_primary)
        if (primaryFld) title = fmtTitle(primaryFld.name, row[primaryFld.name], String(row.id))
      }
    }

    // 分组/颜色
    let groupValue: string | undefined
    let color: string | undefined
    if (groupField) {
      groupValue = fmtGroup(groupField, row[groupField])
      if (groupValue) color = groupColor(groupValue)
    }

    events.push({ row, date, title, groupValue, color })
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

// ── 跨视图共用的事件工具 ──────────────────────────────

/** 把事件按日期字符串分组（MonthView / WeekView 共用）.
 *  filterDays 可选：只保留这些日期范围内的事件（WeekView 过滤本周用）。
 */
function groupEventsByDay(events: CalendarEvent[], filterDays?: Date[]): Map<string, CalendarEvent[]> {
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

/** 构造事件 badge 的统一 style 对象（MonthView / WeekView 共用） */
function eventBadgeStyle(event: CalendarEvent, ds: DensityStyle, lineHeight = 1.3): React.CSSProperties {
  return {
    fontSize: ds.eventFontSize,
    padding: ds.eventPadding,
    borderRadius: ds.eventRadius,
    background: event.color ? `${event.color}15` : '#e6f4ff',
    color: event.color || '#1677ff',
    cursor: 'pointer',
    borderLeft: `3px solid ${event.color || '#1677ff'}`,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    lineHeight,
  }
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
          const mEvents = events.filter((ev) => ev.date.getMonth() === idx)
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
                          const ev = mEvents.find((ev) => fmtDate(ev.date) === dateStr)
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

  // 预计算每天的事件（单点日期，不跨天）
  const eventsByDay = useMemo(() => groupEventsByDay(events), [events])

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
          // 单点日期事件，无需去重
          const dayEvents = eventsByDay.get(dateStr) || []

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
                {dayEvents.length > 3 && isCurrentMonth && (
                  <span style={{ fontSize: ds.cellFontSize - 4, color: '#9ca3af' }}>+{dayEvents.length - 3}</span>
                )}
              </div>

              {/* 事件列表 */}
              <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 1 }}>
                {dayEvents.slice(0, 3).map((ev, idx) => (
                  <div
                    key={`${ev.row.id}-${idx}`}
                    onClick={(e) => { e.stopPropagation(); onEventClick?.(ev.row) }}
                    style={eventBadgeStyle(ev, ds, 1.3)}
                    title={ev.title}
                  >
                    {ev.title}
                  </div>
                ))}
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

  // 按天分组事件（只保留本周范围内的）
  const eventsByDay = useMemo(() => groupEventsByDay(events, weekDays), [events, weekDays])

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
                {dayEvents.length === 0 ? (
                  <div style={{ color: '#d1d5db', textAlign: 'center', fontSize: ds.eventFontSize - 1, padding: `${ds.navPadding + 4}px 0` }}>
                    无
                  </div>
                ) : (
                  dayEvents.map((ev, i) => (
                    <div
                      key={`${ev.row.id}-${i}`}
                      onClick={() => onEventClick?.(ev.row)}
                      style={eventBadgeStyle(ev, ds, 1.4)}
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
  // 稳定的 view_options 引用 — 由 resolveOpts 统一默认值
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, CALENDAR_OPTIONS),
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

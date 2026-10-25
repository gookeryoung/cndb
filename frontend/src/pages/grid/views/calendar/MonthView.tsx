/** 月视图 —— 6×7 网格 + 事件条. */

import { useMemo } from 'react'
import { CheckCircleFilled } from '@ant-design/icons'
import type { RowResponse } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { fmtDate } from '../../cells/dateUtils'
import { CalendarEvent } from './calendarTypes'
import { densityStyle, eventBadgeStyle, getMonthGrid, groupEventsByDay } from './calendarUtils'
import { WEIGHT } from '@/theme/tokens'

export function MonthView({
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
              fontWeight: WEIGHT.semibold,
              fontSize: ds.cellFontSize,
              padding: '4px 0',
              color: idx === 0 || idx === 6 ? '#ff4d4f' : 'var(--cn-text-primary)',
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
          border: '1px solid var(--cn-border)',
          borderRadius: ds.eventRadius + 2,
          overflow: 'hidden',
          background: 'var(--cn-border)',
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
                background: isCurrentMonth ? (isWeekend ? 'var(--cn-bg-subtle)' : 'var(--cn-bg-container)') : 'var(--cn-bg-muted)',
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
                      background: 'var(--cn-brand-color)',
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
                      color: !isCurrentMonth ? 'var(--cn-text-disabled)' : (isWeekend ? '#ff4d4f' : 'var(--cn-text-primary)'),
                    }}
                  >
                    {d.getDate()}
                  </span>
                )}
                {dayEvents.length > 3 && isCurrentMonth && (
                  <span style={{ fontSize: ds.cellFontSize - 4, color: 'var(--cn-text-muted)' }}>+{dayEvents.length - 3}</span>
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
                    {ev.isDone && <CheckCircleFilled style={{ color: '#52c41a', marginLeft: 4, fontSize: ds.eventFontSize }} />}
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

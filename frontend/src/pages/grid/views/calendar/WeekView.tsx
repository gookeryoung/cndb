/** 周视图 —— 7 列单周视图. */

import { useMemo } from 'react'
import { Tag } from 'antd'
import { CheckCircleFilled } from '@ant-design/icons'
import type { RowResponse } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { fmtDate } from '../../cells/dateUtils'
import { CalendarEvent } from './calendarTypes'
import { densityStyle, eventBadgeStyle, getWeekDays, groupEventsByDay } from './calendarUtils'

export function WeekView({
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
                border: '1px solid var(--cn-border)',
                borderRadius: ds.eventRadius + 2,
                background: isWeekend ? 'var(--cn-bg-subtle)' : 'var(--cn-bg-container)',
                overflow: 'hidden',
              }}
            >
              {/* 日期头 */}
              <div
                style={{
                  padding: `${ds.navPadding}px 8px`,
                  borderBottom: '1px solid var(--cn-border)',
                  background: isToday ? 'var(--cn-brand-color)' : (isWeekend ? 'var(--cn-bg-muted)' : 'var(--cn-bg-subtle)'),
                  color: isToday ? '#fff' : (isWeekend ? '#ff4d4f' : 'var(--cn-text-primary)'),
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
                  <div style={{ color: 'var(--cn-text-disabled)', textAlign: 'center', fontSize: ds.eventFontSize - 1, padding: `${ds.navPadding + 4}px 0` }}>
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
                      {ev.isDone && <CheckCircleFilled style={{ color: '#52c41a', marginLeft: 4, fontSize: ds.eventFontSize }} />}
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
      <div style={{ textAlign: 'center', marginTop: 8, fontSize: ds.cellFontSize - 2, color: 'var(--cn-text-muted)' }}>
        本周范围：{weekStart} ~ {weekEnd}
      </div>
    </div>
  )
}

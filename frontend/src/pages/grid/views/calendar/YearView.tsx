/** 年视图 —— 12 个月的迷你网格，点击月份下钻. */

import type { RowResponse } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { fmtDate } from '../../cells/dateUtils'
import { CalendarEvent } from './calendarTypes'
import { densityStyle, getEventDates, getMonthGrid, getYearMonths } from './calendarUtils'
import { WEIGHT } from '@/theme/tokens'

export function YearView({
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
                border: `1px solid ${isCurrentMonth ? 'var(--cn-brand-color)' : 'var(--cn-border)'}`,
                borderRadius: ds.eventRadius + 2,
                padding: ds.navPadding,
                background: isCurrentMonth ? 'var(--cn-bg-subtle)' : 'var(--cn-bg-container)',
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
                  fontWeight: WEIGHT.semibold,
                  fontSize: ds.cellFontSize,
                  color: isCurrentMonth ? 'var(--cn-brand-color)' : 'var(--cn-text-primary)',
                  marginBottom: 4,
                  textAlign: 'center',
                }}
              >
                {idx + 1}月
              </div>

              {/* 迷你日历网格（7 列） */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 1, fontSize: ds.cellFontSize - 4 }}>
                {['日', '一', '二', '三', '四', '五', '六'].map((d) => (
                  <div key={d} style={{ textAlign: 'center', color: 'var(--cn-text-muted)' }}>{d}</div>
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
                        color: !isCurrentMonthCell ? 'var(--cn-text-disabled)' : 'var(--cn-text-primary)',
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
                        <span style={{ background: 'var(--cn-brand-color)', color: '#fff', borderRadius: '50%', padding: '0 2px' }}>{d.getDate()}</span>
                      ) : (
                        d.getDate()
                      )}
                      {hasEvent && isCurrentMonthCell && (
                        <span style={{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)', width: 4, height: 4, background: 'var(--cn-brand-color)', borderRadius: '50%' }} />
                      )}
                    </div>
                  )
                })}
              </div>

              {/* 事件数量 */}
              {mEvents.length > 0 && (
                <div style={{ marginTop: 4, textAlign: 'center', fontSize: ds.cellFontSize - 4, color: 'var(--cn-brand-color)' }}>
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

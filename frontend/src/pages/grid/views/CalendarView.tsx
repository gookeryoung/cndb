import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Segmented, Space, Tooltip, Empty } from 'antd'
import {
  LeftOutlined,
  RightOutlined,
  CalendarOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { fmtDate } from '../cells/dateUtils'
import { resolveOpts, CALENDAR_OPTIONS } from '../view-config/viewOptionSchema'
import { resolveDoneCtx } from './kanbanBoard'
import { buildEvents, densityStyle, getWeekDays } from './calendar/calendarUtils'
import { YearView } from './calendar/YearView'
import { MonthView } from './calendar/MonthView'
import { WeekView } from './calendar/WeekView'

// ── 类型定义 ──────────────────────────────────────────

type CalendarMode = 'year' | 'month' | 'week'

interface CalendarViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

export default function CalendarView({ rows, fields, view, density, onRowClick }: CalendarViewProps) {
  // 稳定的 view_options 引用 — 由 resolveOpts 统一默认值
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, CALENDAR_OPTIONS),
    [view?.view_options],
  )

  // 当前"注视日期"——所有层级导航围绕此日期展开
  // 初始化时：优先 today，但如果 events 非空且 today 的月份没有事件，则跳到第一个有事件的日期
  const [focusDate, setFocusDate] = useState<Date>(() => new Date())
  const [mode, setMode] = useState<CalendarMode>(() => (opts.calendar_mode as CalendarMode) || 'month')

  // 从 options 中解析 show_weekend 等偏好（留作未来扩展）
  void opts.show_weekend

  const year = focusDate.getFullYear()
  const month = focusDate.getMonth()

  // 构建事件列表（完成标志判定与看板共用 resolveDoneCtx/isDoneRow）
  const doneCtx = useMemo(() => resolveDoneCtx(opts, fields), [opts, fields])
  const events = useMemo(() => buildEvents(rows, fields, opts, doneCtx), [rows, fields, opts, doneCtx])

  // events 首次非空时，若当前 focusDate 所在月无事件，自动跳到第一个有事件的日期
  // 仅在首次有效渲染时触发一次，用户手动翻月后不再自动修正
  const autoFocusDoneRef = useRef(false)
  useEffect(() => {
    if (autoFocusDoneRef.current) return
    if (events.length === 0) return
    const target = events[0].date
    // 检查当前 focusDate 月是否有任何事件
    const hasEventInMonth = events.some(
      (ev) =>
        ev.date.getFullYear() === focusDate.getFullYear() &&
        ev.date.getMonth() === focusDate.getMonth(),
    )
    if (!hasEventInMonth) {
      autoFocusDoneRef.current = true
      setFocusDate(target)
    } else {
      // 已有事件，不再需要自动跳转，避免后续重复修正
      autoFocusDoneRef.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events])

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
              ? '当前时间范围内没有事件，试试切换月份或回到今天'
              : '日历视图需要配置「开始时间字段」（start_field）：到视图设置中选择表中的日期字段即可显示'
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
          borderBottom: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-container)',
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
          <CalendarOutlined style={{ marginRight: 6, color: 'var(--cn-brand-color)' }} />
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
        <div style={{ marginLeft: 'auto', fontSize: ds.navFontSize, color: 'var(--cn-text-muted)' }}>
          共 {events.length} 个事件
        </div>
      </div>

      {/* 日历主体 */}
      <div style={{ flex: 1, overflow: 'auto', background: 'var(--cn-bg-page)' }}>
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

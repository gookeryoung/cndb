/** 甘特图视图组件 — 时间轴 + 任务进度条.
 *
 * view_options 配置字段（由 GANTT_OPTIONS schema 定义）:
 * - start_date_field:  任务开始日期（date/datetime，必填）
 * - end_date_field:    任务结束日期（date/datetime，必填）
 * - actual_end_field:  实际完成日期（可选，对比计划/实际）
 * - title_field:       任务名称字段（可选，留空自动推断）
 * - group_field:       分组/着色字段（select，可选）
 * - progress_field:    进度百分比字段（number，0-100）
 * - assignee_field:    负责人字段（可选）
 * - time_scale:        时间粒度 'day' | 'week' | 'month' | 'quarter'（默认 'month'）
 * - show_today_line:   是否显示今日标线（默认 true）
 */

import { useMemo, useState } from 'react'
import { Segmented, Button, Tooltip, Empty } from 'antd'
import { LeftOutlined, RightOutlined, ReloadOutlined, CalendarOutlined } from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, GANTT_OPTIONS, resolveAutoField, findOptionSchema } from './viewOptionSchema'
import { formatFieldDisplayValue, getLinkFirstLabel, getMultiSelectFirstLabel, getSelectLabel } from './fieldValueFormat'
import { parseDate, fmtDate } from './dateUtils'

// ── 类型定义 ──────────────────────────────────────────

interface GanttTask {
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

type TimeScale = 'day' | 'week' | 'month' | 'quarter'

interface GanttViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

// ── 预设色板（复用 CalendarView 风格） ────────────────

const GROUP_PALETTE = [
  '#1677ff', '#f5222d', '#fa8c16', '#52c41a', '#722ed1',
  '#eb2f96', '#13c2c2', '#faad14', '#2f54eb', '#a0d911',
]

function groupColor(value: string): string {
  let h = 0
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) & 0x7fffffff
  return GROUP_PALETTE[h % GROUP_PALETTE.length]
}

// ── 密度样式 ──────────────────────────────────────────

function densityStyle(density: Density) {
  if (density === 'compact') {
    return {
      rowHeight: 32,
      headerHeight: 32,
      leftColWidth: 220,
      barHeight: 18,
      titleFontSize: 12,
      metaFontSize: 10,
      headerFontSize: 11,
    }
  }
  if (density === 'spacious') {
    return {
      rowHeight: 56,
      headerHeight: 40,
      leftColWidth: 280,
      barHeight: 28,
      titleFontSize: 14,
      metaFontSize: 12,
      headerFontSize: 13,
    }
  }
  return {
    rowHeight: 44,
    headerHeight: 36,
    leftColWidth: 250,
    barHeight: 24,
    titleFontSize: 13,
    metaFontSize: 11,
    headerFontSize: 12,
  }
}

// ── 时间轴计算 ────────────────────────────────────────

/** 计算两个日期之间的天数差（含当天） */
function daysBetween(a: Date, b: Date): number {
  const diff = b.getTime() - a.getTime()
  return Math.max(1, Math.round(diff / (1000 * 60 * 60 * 24)) + 1)
}

/** 根据 tasks 计算时间轴范围（向前扩展 5 天，向后扩展 15 天以留出余量） */
function computeTimeRange(tasks: GanttTask[]): { min: Date; max: Date } | null {
  if (tasks.length === 0) return null
  let min = tasks[0].start
  let max = tasks[0].end
  for (const t of tasks) {
    if (t.start < min) min = t.start
    if (t.end > max) max = t.end
  }
  // 向前 5 天，向后 15 天
  const paddedMin = new Date(min)
  paddedMin.setDate(paddedMin.getDate() - 5)
  const paddedMax = new Date(max)
  paddedMax.setDate(paddedMax.getDate() + 15)
  return { min: paddedMin, max: paddedMax }
}

/** 根据时间刻度生成时间轴 header 分段 */
interface TimelineSegment {
  label: string
  date: Date
  width: number  // 像素宽度
  days: number   // 覆盖天数
}

function buildTimeline(
  range: { min: Date; max: Date },
  scale: TimeScale,
  pxPerDay: number,
): TimelineSegment[] {
  const segments: TimelineSegment[] = []
  const totalDays = daysBetween(range.min, range.max)

  if (scale === 'day') {
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(range.min)
      d.setDate(d.getDate() + i)
      segments.push({
        label: `${d.getMonth() + 1}/${d.getDate()}`,
        date: d,
        width: pxPerDay,
        days: 1,
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
      const label = `${weekStart.getMonth() + 1}/${weekStart.getDate()}`
      segments.push({ label, date: weekStart, width: days * pxPerDay, days })
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
      const fullDays = daysBetween(
        cursor,
        new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0),
      )
      segments.push({
        label: `${cursor.getFullYear()}年${cursor.getMonth() + 1}月`,
        date: cursor,
        width: fullDays * pxPerDay,
        days: fullDays,
      })
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
      // 但我们需要的是实际可见区间的天数 * pxPerDay，不是整月
      segments[segments.length - 1].width = days * pxPerDay
    }
  } else { // quarter
    let cursor = new Date(range.min.getFullYear(), Math.floor(range.min.getMonth() / 3) * 3, 1)
    while (cursor <= range.max) {
      const qEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 3, 0)
      const days = daysBetween(
        cursor < range.min ? range.min : cursor,
        qEnd > range.max ? range.max : qEnd,
      )
      const qNum = Math.floor(cursor.getMonth() / 3) + 1
      segments.push({
        label: `${cursor.getFullYear()} Q${qNum}`,
        date: cursor,
        width: days * pxPerDay,
        days,
      })
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 3, 1)
    }
  }

  return segments
}

/** 根据 pxPerDay 自适应：如果总宽度太大则缩小，如果太小则放大 */
function computePxPerDay(range: { min: Date; max: Date }, scale: TimeScale): number {
  const totalDays = daysBetween(range.min, range.max)
  let basePx = 6 // 默认 6px/天

  // 根据刻度调整基础值
  if (scale === 'day') basePx = 18  // 天刻度要更宽
  else if (scale === 'week') basePx = 10
  else if (scale === 'month') basePx = 4
  else basePx = 1.5 // quarter 最窄

  const totalWidth = totalDays * basePx

  // 太宽了 → 缩小
  if (totalWidth > 3000) {
    basePx = Math.max(1.5, 3000 / totalDays)
  }
  // 太窄了 → 放大
  if (totalWidth < 600) {
    basePx = Math.min(20, 600 / totalDays)
  }

  return basePx
}

// ── 任务构建 ──────────────────────────────────────────

/** 将 rows 转成 GanttTask 列表 */
function buildGanttTasks(
  rows: RowResponse[],
  fields: Field[],
  opts: Record<string, unknown>,
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>,
): GanttTask[] {
  const startField = opts.start_date_field as string
  const endField = opts.end_date_field as string
  const actualEndField = opts.actual_end_field as string | undefined
  const groupField = opts.group_field as string | undefined
  const progressField = opts.progress_field as string | undefined
  const assigneeField = opts.assignee_field as string | undefined

  if (!startField || !endField) return []

  // title_field 自动推断
  let titleField = opts.title_field as string | undefined
  if (!titleField) {
    titleField = resolveAutoField(fields, findOptionSchema('gantt', 'title_field'))
  }
  if (!titleField) titleField = fields[0]?.name || 'id'

  const fieldMap = new Map<string, Field>(fields.map(f => [f.name, f]))

  const fmtGroup = (name: string, raw: unknown): string | undefined => {
    const fd = fieldMap.get(name)
    if (!fd) return raw != null && raw !== '' ? String(raw) : undefined
    if (fd.field_type === 'link') return getLinkFirstLabel(raw) || undefined
    if (fd.field_type === 'multi_select' || fd.field_type === 'multiselect') return getMultiSelectFirstLabel(raw) || undefined
    if (fd.field_type === 'select') return getSelectLabel(fd, raw) || undefined
    return formatFieldDisplayValue(fd, raw) || undefined
  }

  const tasks: GanttTask[] = []
  for (const row of rows) {
    const start = parseDate(row[startField])
    const end = parseDate(row[endField])
    if (!start || !end) continue
    if (end < start) continue // 跳过非法区间

    // 标题
    const titleFd = fieldMap.get(titleField)
    const title = titleFd
      ? formatFieldDisplayValue(titleFd, row[titleField]) || String(row.id)
      : String(row[titleField] ?? row.id)

    // 分组/颜色
    let groupValue: string | undefined
    let color: string | undefined
    if (groupField) {
      groupValue = fmtGroup(groupField, row[groupField])
      if (groupValue) color = groupColor(groupValue)
    }

    // 进度
    let progress = 0
    if (progressField) {
      const v = Number(row[progressField])
      if (Number.isFinite(v)) progress = Math.max(0, Math.min(100, v))
    }

    // 负责人
    let assignee: string | undefined
    if (assigneeField) {
      const afd = fieldMap.get(assigneeField)
      assignee = afd
        ? formatFieldDisplayValue(afd, row[assigneeField]) || undefined
        : row[assigneeField] ? String(row[assigneeField]) : undefined
    }

    // 实际完成日期
    const actualEnd = actualEndField ? parseDate(row[actualEndField]) : null

    tasks.push({ row, start, end, actualEnd, title, groupValue, color, progress, assignee })
  }

  // 排序：先按分组（如果有），再按开始日期
  tasks.sort((a, b) => {
    // 应用用户的 sortings
    if (sortings && sortings.length > 0) {
      for (const s of sortings) {
        const field = fieldMap.get(s.field_name)
        if (!field) continue
        const va = a.row[s.field_name]
        const vb = b.row[s.field_name]
        if (va == null && vb == null) continue
        if (va == null) return s.direction === 'asc' ? 1 : -1
        if (vb == null) return s.direction === 'asc' ? -1 : 1
        let cmp = 0
        if (['date', 'datetime'].includes(field.field_type)) {
          cmp = parseDate(va)!.getTime() - parseDate(vb)!.getTime()
        } else if (['number', 'decimal', 'float', 'percentage'].includes(field.field_type)) {
          cmp = Number(va) - Number(vb)
        } else {
          cmp = String(va).localeCompare(String(vb), 'zh-CN')
        }
        if (cmp !== 0) return s.direction === 'asc' ? cmp : -cmp
      }
    }

    // 默认排序：按分组 → 开始日期
    const ga = a.groupValue || ''
    const gb = b.groupValue || ''
    if (ga !== gb) return ga.localeCompare(gb, 'zh-CN')
    return a.start.getTime() - b.start.getTime()
  })

  return tasks
}

// ── 甘特条渲染 ────────────────────────────────────────

interface GanttBarProps {
  task: GanttTask
  range: { min: Date }
  pxPerDay: number
  barHeight: number
  onRowClick?: (r: RowResponse) => void
}

function GanttBar({ task, range, pxPerDay, barHeight, onRowClick }: GanttBarProps) {
  // 计算相对于 range.min 的偏移
  const offsetDays = daysBetween(range.min, task.start) - 1
  const durationDays = daysBetween(task.start, task.end)
  const left = offsetDays * pxPerDay
  const width = Math.max(pxPerDay, durationDays * pxPerDay)

  // 进度宽度
  const progressWidth = (task.progress / 100) * width

  // 实际完成条（如果有 actualEnd）
  let actualEndWidth: number | null = null
  if (task.actualEnd) {
    const actualDuration = daysBetween(task.start, task.actualEnd)
    if (task.actualEnd >= task.start) {
      actualEndWidth = Math.max(pxPerDay, actualDuration * pxPerDay)
    }
  }

  // 甘特条颜色
  const barColor = task.color || 'var(--cn-brand-color)'
  const barBg = `${barColor}30` // 带透明度

  return (
    <div
      data-testid="gantt-bar"
      data-row-id={task.row.id}
      onClick={(e) => { e.stopPropagation(); onRowClick?.(task.row) }}
      style={{
        position: 'absolute',
        left,
        top: '50%',
        transform: 'translateY(-50%)',
        height: barHeight,
        width: Math.max(width, pxPerDay),
        borderRadius: 4,
        background: barBg,
        border: `1px solid ${barColor}`,
        cursor: 'pointer',
        overflow: 'hidden',
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = `0 2px 8px ${barColor}50`
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'none'
      }}
      title={`${task.title}\n${fmtDate(task.start)} ~ ${fmtDate(task.end)}\n进度: ${task.progress}%`}
    >
      {/* 进度填充 */}
      {task.progress > 0 && (
        <div
          style={{
            height: '100%',
            width: `${task.progress}%`,
            maxWidth: progressWidth,
            background: barColor,
            borderRadius: 3,
            transition: 'width 0.2s',
          }}
        />
      )}

      {/* 实际完成标记（虚线框） */}
      {actualEndWidth != null && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            height: '100%',
            width: actualEndWidth,
            borderLeft: `2px dashed ${barColor}`,
            opacity: 0.7,
            pointerEvents: 'none',
          }}
        />
      )}

      {/* 进度文本 */}
      {task.progress > 20 && (
        <span
          style={{
            position: 'absolute',
            top: '50%',
            left: 6,
            transform: 'translateY(-50%)',
            fontSize: 10,
            color: task.progress > 50 ? '#fff' : barColor,
            fontWeight: 500,
            whiteSpace: 'nowrap',
            lineHeight: 1,
          }}
        >
          {task.progress}%
        </span>
      )}
    </div>
  )
}

// ── 今日标线 ──────────────────────────────────────────

function TodayLine({
  range,
  pxPerDay,
}: {
  range: { min: Date; max: Date }
  pxPerDay: number
}) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  if (today < range.min || today > range.max) return null

  const offsetDays = daysBetween(range.min, today) - 1
  const left = offsetDays * pxPerDay + pxPerDay / 2

  return (
    <div
      data-testid="gantt-today-line"
      style={{
        position: 'absolute',
        left,
        top: 0,
        bottom: 0,
        width: 2,
        background: '#ff4d4f',
        zIndex: 2,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: -1,
          left: -4,
          width: 10,
          height: 10,
          background: '#ff4d4f',
          borderRadius: '50%',
        }}
      />
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────

export default function GanttView({
  rows,
  fields,
  view,
  density,
  sortings,
  onRowClick,
}: GanttViewProps & {
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>
}) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, GANTT_OPTIONS),
    [view?.view_options],
  )

  const ds = densityStyle(density)
  const scale = (opts.time_scale as TimeScale) || 'month'
  const showToday = opts.show_today_line !== false
  const groupField = opts.group_field as string | undefined

  // 构建任务列表
  const tasks = useMemo(
    () => buildGanttTasks(rows, fields, opts, sortings),
    [rows, fields, opts, sortings],
  )

  // 计算时间轴
  const timeRange = useMemo(
    () => computeTimeRange(tasks),
    [tasks],
  )

  // 计算每日像素和生成时间轴
  const pxPerDay = useMemo(
    () => timeRange ? computePxPerDay(timeRange, scale) : 6,
    [timeRange, scale],
  )

  const timeline = useMemo(
    () => timeRange ? buildTimeline(timeRange, scale, pxPerDay) : [],
    [timeRange, scale, pxPerDay],
  )

  const totalTimelineWidth = timeline.reduce((sum, t) => sum + t.width, 0)

  // 导航状态（时间轴平移偏移）
  const [scrollX, setScrollX] = useState(0)

  // 按分组聚合（用于左侧分组分隔）
  const groupedTasks = useMemo(() => {
    const groups: Array<{ key: string; label: string; tasks: GanttTask[]; color: string }> = []
    for (const t of tasks) {
      const gkey = t.groupValue || '__nogroup__'
      let g = groups.find(g => g.key === gkey)
      if (!g) {
        g = { key: gkey, label: t.groupValue || '未分组', tasks: [], color: groupColor(gkey) }
        groups.push(g)
      }
      g.tasks.push(t)
    }
    return groups
  }, [tasks])

  // 空状态
  const startField = opts.start_date_field as string | undefined
  const endField = opts.end_date_field as string | undefined
  if (!startField || !endField) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="甘特图视图需要配置 start_date_field（开始日期）和 end_date_field（结束日期）" />
      </div>
    )
  }
  if (tasks.length === 0 || !timeRange) {
    return (
      <div style={{ padding: 24 }}>
        <Empty
          description={
            rows.length === 0
              ? '暂无数据'
              : '当前时间范围内没有有效任务（请检查开始/结束日期字段）'
          }
        />
      </div>
    )
  }

  // 导航函数
  const scrollTimeline = (direction: -1 | 1) => {
    setScrollX(prev => Math.max(0, prev + direction * 200))
  }

  return (
    <div data-testid="gantt-view" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 工具栏 */}
      <div
        style={{
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          borderBottom: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-container)',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: ds.headerFontSize + 2, display: 'flex', alignItems: 'center', gap: 6 }}>
          <CalendarOutlined style={{ color: 'var(--cn-brand-color)' }} />
          甘特图视图
        </div>

        <Segmented
          size="small"
          value={scale}
          onChange={() => { /* scale 由 options 控制，此处留作未来扩展 */ }}
          options={[
            { value: 'day', label: '天' },
            { value: 'week', label: '周' },
            { value: 'month', label: '月' },
            { value: 'quarter', label: '季' },
          ]}
        />

        <div style={{ marginLeft: 'auto', fontSize: ds.headerFontSize, color: 'var(--cn-text-muted)' }}>
          共 {tasks.length} 个任务 · {groupedTasks.length} 个分组
        </div>
      </div>

      {/* 时间轴 header */}
      <div
        style={{
          display: 'flex',
          borderBottom: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-subtle)',
          height: ds.headerHeight,
          flexShrink: 0,
        }}
      >
        {/* 左侧固定标题列 */}
        <div
          style={{
            width: ds.leftColWidth,
            minWidth: ds.leftColWidth,
            padding: '0 12px',
            display: 'flex',
            alignItems: 'center',
            borderRight: '1px solid var(--cn-border)',
            fontWeight: 600,
            fontSize: ds.headerFontSize,
            background: 'var(--cn-bg-container)',
          }}
        >
          任务名称
        </div>

        {/* 右侧时间轴 header */}
        <div
          style={{
            flex: 1,
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <div
            style={{
              display: 'flex',
              height: '100%',
              transform: `translateX(${-scrollX}px)`,
              transition: 'transform 0.2s',
              minWidth: totalTimelineWidth,
            }}
          >
            {timeline.map((seg, idx) => (
              <div
                key={idx}
                style={{
                  width: seg.width,
                  minWidth: seg.width,
                  padding: '0 8px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRight: '1px solid var(--cn-border)',
                  fontSize: ds.headerFontSize,
                  color: 'var(--cn-text-muted)',
                  flexShrink: 0,
                }}
              >
                {seg.label}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 任务行区域 */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {groupedTasks.map((group) => (
          <div key={group.key}>
            {/* 分组标题（有 group_field 时显示） */}
            {groupField && (
              <div
                style={{
                  padding: '4px 12px',
                  background: 'var(--cn-bg-subtle)',
                  borderBottom: '1px solid var(--cn-border)',
                  fontSize: ds.metaFontSize,
                  fontWeight: 600,
                  color: group.color || 'var(--cn-text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: group.color || 'var(--cn-text-muted)',
                  }}
                />
                {group.label}
                <span style={{ color: 'var(--cn-text-muted)', fontWeight: 400 }}>
                  ({group.tasks.length})
                </span>
              </div>
            )}

            {/* 任务行 */}
            {group.tasks.map((task) => (
              <div
                key={task.row.id}
                onClick={() => onRowClick?.(task.row)}
                style={{
                  display: 'flex',
                  height: ds.rowHeight,
                  borderBottom: '1px solid var(--cn-border)',
                  cursor: 'pointer',
                  position: 'relative',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--cn-bg-subtle)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = ''
                }}
              >
                {/* 左侧任务名称 */}
                <div
                  style={{
                    width: ds.leftColWidth,
                    minWidth: ds.leftColWidth,
                    padding: '0 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    borderRight: '1px solid var(--cn-border)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      fontSize: ds.titleFontSize,
                      fontWeight: 500,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {task.title}
                  </div>
                  {task.assignee && (
                    <div
                      style={{
                        fontSize: ds.metaFontSize,
                        color: 'var(--cn-text-muted)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      👤 {task.assignee}
                    </div>
                  )}
                </div>

                {/* 右侧甘特条区域 */}
                <div
                  style={{
                    flex: 1,
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      position: 'relative',
                      height: '100%',
                      minWidth: totalTimelineWidth,
                      transform: `translateX(${-scrollX}px)`,
                      transition: 'transform 0.2s',
                    }}
                  >
                    {/* 背景网格线 */}
                    <div style={{ position: 'absolute', inset: 0 }}>
                      {timeline.map((seg, idx) => {
                        const left = timeline.slice(0, idx).reduce((s, t) => s + t.width, 0)
                        return (
                          <div
                            key={idx}
                            style={{
                              position: 'absolute',
                              left,
                              top: 0,
                              bottom: 0,
                              width: seg.width,
                              borderRight: '1px solid var(--cn-border)',
                              pointerEvents: 'none',
                            }}
                          />
                        )
                      })}
                    </div>

                    {/* 甘特条 */}
                    <GanttBar
                      task={task}
                      range={timeRange}
                      pxPerDay={pxPerDay}
                      barHeight={ds.barHeight}
                      onRowClick={onRowClick}
                    />

                    {/* 今日标线（每行都画，否则视觉不连贯） */}
                    {showToday && <TodayLine range={timeRange} pxPerDay={pxPerDay} />}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 底部导航栏 */}
      <div
        style={{
          padding: '6px 12px',
          borderTop: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-container)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexShrink: 0,
        }}
      >
        <Tooltip title="时间轴左移">
          <Button size="small" icon={<LeftOutlined />} onClick={() => scrollTimeline(-1)} />
        </Tooltip>
        <Tooltip title="时间轴右移">
          <Button size="small" icon={<RightOutlined />} onClick={() => scrollTimeline(1)} />
        </Tooltip>
        <Tooltip title="重置位置">
          <Button size="small" icon={<ReloadOutlined />} onClick={() => setScrollX(0)} />
        </Tooltip>
        <span style={{ fontSize: ds.metaFontSize, color: 'var(--cn-text-muted)' }}>
          {fmtDate(timeRange.min)} ~ {fmtDate(timeRange.max)}
        </span>
      </div>
    </div>
  )
}

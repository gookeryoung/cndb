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
 *
 * 滚动策略：用一个真实的 overflow-x: auto 横向滚动容器包住右侧全部时间轴内容，
 * header 和 body 各自独立但横向同步；同时支持鼠标滚轮转横向 + 滚动到今天按钮。
 */

import { memo, useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { Segmented, Button, Tooltip, Empty } from 'antd'
import { LeftOutlined, RightOutlined, ReloadOutlined, CalendarOutlined, HomeOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, GANTT_OPTIONS, resolveAutoField, findOptionSchema } from '../view-config/viewOptionSchema'
import { formatFieldDisplayValue, getLinkFirstLabel, getMultiSelectFirstLabel, getSelectLabel } from '../cells/fieldValueFormat'
import { parseDate, fmtDate } from '../cells/dateUtils'
import {
  type GanttTask, type TimeScale,
  daysBetween, computeTimeRange, ZOOM_LEVELS,
  buildDualTimeline, selectZoomLevelForScale, autoAdjustLevel,
} from './ganttTimeline'

// ── 类型定义 ──────────────────────────────────────────

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
      groupHeaderHeight: 34,
      wbsIndent: 16,
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
      groupHeaderHeight: 44,
      wbsIndent: 20,
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
    groupHeaderHeight: 38,
    wbsIndent: 18,
  }
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

const GanttBar = memo(function GanttBar({ task, range, pxPerDay, barHeight, onRowClick }: GanttBarProps) {
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
})

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
  const defaultScale = (opts.time_scale as TimeScale) || 'month'
  const [scale, setScale] = useState<TimeScale>(defaultScale)
  const [zoomLevel, setZoomLevel] = useState<number | null>(null)

  // 切换 view 时，本地 scale + zoomLevel 同步到新 view 的默认值
  useEffect(() => {
    setScale(defaultScale)
    setZoomLevel(null) // 触发 selectZoomLevelForScale 重新计算
  }, [defaultScale])

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

  // 根据 scale + 时间跨度自动选初始 zoomLevel
  const totalDays = timeRange ? daysBetween(timeRange.min, timeRange.max) : 365
  const resolvedLevel = zoomLevel ?? (timeRange ? selectZoomLevelForScale(scale, totalDays) : 2)

  // 只有用户还没手动调过 zoom 时才做视口宽度微调（避免覆盖用户手动选择）
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1200
  const finalLevel = zoomLevel == null && timeRange
    ? autoAdjustLevel(resolvedLevel, totalDays, viewportWidth)
    : resolvedLevel

  // 构建双层时间轴
  const dualTimeline = useMemo(
    () => timeRange ? buildDualTimeline(timeRange, finalLevel) : {
      anchorSegments: [], currentSegments: [], pxPerDay: 6, level: 2, levelDef: ZOOM_LEVELS[2],
    },
    [timeRange, finalLevel],
  )

  const { anchorSegments, currentSegments, pxPerDay, levelDef } = dualTimeline
  const totalTimelineWidth = anchorSegments.reduce((s, t) => s + t.width, 0)

  // ── 滚动容器 ref —— 整个右侧时间轴用真实 overflow-x: auto ──
  const hScrollRef = useRef<HTMLDivElement>(null)

  const scrollTo = useCallback((delta: number) => {
    const el = hScrollRef.current
    if (!el) return
    el.scrollBy({ left: delta, behavior: 'smooth' })
  }, [])

  const scrollToToday = useCallback(() => {
    const el = hScrollRef.current
    if (!el || !timeRange) return
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    if (today < timeRange.min || today > timeRange.max) return
    const offsetDays = daysBetween(timeRange.min, today) - 1
    const todayLeft = offsetDays * pxPerDay
    const target = Math.max(0, todayLeft - el.clientWidth / 2)
    el.scrollTo({ left: target, behavior: 'smooth' })
  }, [timeRange, pxPerDay])

  // 滚轮转横向
  useEffect(() => {
    const el = hScrollRef.current
    if (!el) return
    const handler = (e: WheelEvent) => {
      if (e.shiftKey) return
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault()
        el.scrollLeft += e.deltaY
      }
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [totalTimelineWidth])

  // 按分组聚合（用于左侧分组分隔 + WBS 编号）
  const groupedTasks = useMemo(() => {
    const groups: Array<{
      key: string
      label: string
      tasks: GanttTask[]
      color: string
      index: number   // 组序号（1-based，用于 WBS 编号）
    }> = []
    for (const t of tasks) {
      const gkey = t.groupValue || '__nogroup__'
      let g = groups.find(g => g.key === gkey)
      if (!g) {
        g = {
          key: gkey,
          label: t.groupValue || '未分组',
          tasks: [],
          color: groupColor(gkey),
          index: groups.length + 1,
        }
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

  // 导航步长自适应：视口宽度的 30%
  const navStep = typeof window !== 'undefined' ? Math.max(120, Math.floor(window.innerWidth * 0.3)) : 200

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
          flexShrink: 0,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: ds.headerFontSize + 2, display: 'flex', alignItems: 'center', gap: 6 }}>
          <CalendarOutlined style={{ color: 'var(--cn-brand-color)' }} />
          甘特图视图
        </div>

        <div data-testid="gantt-scale-switch">
          <Segmented
            size="small"
            value={scale}
            onChange={(v) => {
              const newScale = v as TimeScale
              setScale(newScale)
              setZoomLevel(null) // 让 zoomLevel 重新按 newScale 自动选择
            }}
            options={[
              { value: 'day', label: '天' },
              { value: 'week', label: '周' },
              { value: 'month', label: '月' },
              { value: 'quarter', label: '季' },
            ]}
          />
        </div>

        {/* 缩放控件 —— 连续缩放 8 档 */}
        <div
          data-testid="gantt-scale-info"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '0 8px',
            height: 24,
            borderRadius: 4,
            border: '1px solid var(--cn-border)',
            fontSize: ds.headerFontSize,
            color: 'var(--cn-text-muted)',
            background: 'var(--cn-bg-subtle)',
          }}
          title={`${levelDef.name} · ${pxPerDay.toFixed(1)} px/天`}
        >
          <Button
            size="small"
            type="text"
            icon={<ZoomOutOutlined />}
            disabled={finalLevel <= 0}
            onClick={() => setZoomLevel(finalLevel - 1)}
            title="缩小"
          />
          <span style={{ minWidth: 44, textAlign: 'center', fontWeight: 500, color: 'var(--cn-text)' }}>
            {levelDef.name}
          </span>
          <Button
            size="small"
            type="text"
            icon={<ZoomInOutlined />}
            disabled={finalLevel >= ZOOM_LEVELS.length - 1}
            onClick={() => setZoomLevel(finalLevel + 1)}
            title="放大"
          />
        </div>

        <div style={{ marginLeft: 'auto', fontSize: ds.headerFontSize, color: 'var(--cn-text-muted)' }}>
          共 {tasks.length} 个任务 · {groupedTasks.length} 个分组
        </div>
      </div>

      {/* ─── 主体：左列固定 + 右列横向可滚动 ─── */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左侧固定列（header + body 合并为一个区域） */}
        <div
          style={{
            width: ds.leftColWidth,
            minWidth: ds.leftColWidth,
            borderRight: '1px solid var(--cn-border)',
            background: 'var(--cn-bg-container)',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
            overflow: 'hidden',
          }}
        >
          {/* 左侧 header */}
          <div
            style={{
              height: ds.headerHeight,
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              padding: '0 12px',
              fontWeight: 600,
              fontSize: ds.headerFontSize,
              borderBottom: '1px solid var(--cn-border)',
              background: 'var(--cn-bg-subtle)',
            }}
          >
            {groupField ? 'WBS 分解' : '任务名称'}
          </div>

          {/* 左侧 body —— 跟随右侧纵向滚动 */}
          <LeftColBody
            groupedTasks={groupedTasks}
            ds={ds}
            groupField={!!groupField}
            onRowClick={onRowClick}
            rightScrollRef={hScrollRef}
          />
        </div>

        {/* 右侧时间轴区域 —— 单一真实横向滚动容器 */}
        <div
          ref={hScrollRef}
          style={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            overflowX: 'auto',
            overflowY: 'hidden',
            position: 'relative',
          }}
        >
          {/* header —— 双层 */}
          <div style={{ flexShrink: 0, minWidth: totalTimelineWidth }}>
            {/* 上层：锚定层（month / year）—— 合并渲染 */}
            <div
              data-testid="gantt-header-row"
              data-layer="anchor"
              style={{
                height: ds.headerHeight,
                position: 'relative',
                minWidth: totalTimelineWidth,
                borderBottom: '1px solid var(--cn-border)',
                background: 'var(--cn-bg-container)',
              }}
            >
              {anchorSegments.map((seg) => (
                <div
                  key={`a-${seg.left}`}
                  data-testid={seg.showLabel ? 'gantt-timeline-label' : undefined}
                  data-layer="anchor"
                  style={{
                    position: 'absolute',
                    left: seg.left,
                    top: 0,
                    bottom: 0,
                    width: seg.width,
                    padding: '0 6px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-start',
                    borderRight: '1px solid var(--cn-border)',
                    fontSize: ds.headerFontSize,
                    fontWeight: 600,
                    color: 'var(--cn-text)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {seg.showLabel ? seg.label : null}
                </div>
              ))}
            </div>

            {/* 下层：当前刻度层（day / week / month / quarter）—— flex 布局 */}
            <div
              data-testid="gantt-header-row"
              data-layer="current"
              style={{
                height: ds.headerHeight,
                minWidth: totalTimelineWidth,
                display: 'flex',
                background: 'var(--cn-bg-subtle)',
              }}
            >
              {currentSegments.map((seg) => (
                <div
                  key={`c-${seg.left}`}
                  data-testid={seg.showLabel ? 'gantt-timeline-label' : undefined}
                  data-layer="current"
                  style={{
                    width: seg.width,
                    minWidth: seg.width,
                    padding: '0 3px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRight: `1px solid ${levelDef.anchorScale === 'year' ? 'var(--cn-border)' : 'var(--cn-border-secondary, #f0f0f0)'}`,
                    fontSize: ds.headerFontSize,
                    color: 'var(--cn-text-muted)',
                    flexShrink: 0,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                  }}
                >
                  {seg.showLabel ? seg.label : null}
                </div>
              ))}
            </div>
          </div>

          {/* body 行区 —— 垂直滚动 */}
          <div
            style={{
              position: 'relative',
              flex: 1,
              overflow: 'auto',
              minWidth: totalTimelineWidth,
            }}
          >
            {/* 时间轴网格背景层 —— 双层：主分隔（锚定粒度深色）+ 次分隔（当前粒度浅色） */}
            <div
              aria-hidden
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: totalTimelineWidth,
                height: '100%',
                pointerEvents: 'none',
                zIndex: 0,
              }}
            >
              {/* 主分隔线：锚定粒度 */}
              {anchorSegments.map((seg) => (
                <div
                  key={`ag-${seg.left}`}
                  style={{
                    position: 'absolute',
                    left: seg.left,
                    top: 0,
                    bottom: 0,
                    width: seg.width,
                    borderRight: '1px solid var(--cn-border)',
                  }}
                />
              ))}
              {/* 次分隔线：当前粒度（仅当粒度 < 锚定粒度时渲染） */}
              {levelDef.anchorScale === 'month' && levelDef.currentScale === 'day' && currentSegments.map((seg, i) => (
                i < currentSegments.length - 1 ? (
                  <div
                    key={`cg-${seg.left}`}
                    style={{
                      position: 'absolute',
                      left: seg.left + seg.width,
                      top: 0,
                      bottom: 0,
                      width: 0,
                      borderRight: '1px dashed var(--cn-border-secondary, #eee)',
                    }}
                  />
                ) : null
              ))}
              {levelDef.anchorScale === 'month' && levelDef.currentScale === 'week' && currentSegments.map((seg, i) => (
                i < currentSegments.length - 1 ? (
                  <div
                    key={`cg-${seg.left}`}
                    style={{
                      position: 'absolute',
                      left: seg.left + seg.width,
                      top: 0,
                      bottom: 0,
                      width: 0,
                      borderRight: '1px dashed var(--cn-border-secondary, #eee)',
                    }}
                  />
                ) : null
              ))}
              {showToday && timeRange && <TodayLine range={timeRange} pxPerDay={pxPerDay} />}
            </div>

            {/* 分组 + 任务行 */}
            {groupedTasks.map((group) => (
              <GroupBlock
                key={group.key}
                group={group}
                ds={ds}
                groupField={!!groupField}
                timeRange={timeRange!}
                pxPerDay={pxPerDay}
                totalTimelineWidth={totalTimelineWidth}
                onRowClick={onRowClick}
              />
            ))}
          </div>
        </div>
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
          <Button size="small" icon={<LeftOutlined />} onClick={() => scrollTo(-navStep)} />
        </Tooltip>
        <Tooltip title="时间轴右移">
          <Button size="small" icon={<RightOutlined />} onClick={() => scrollTo(navStep)} />
        </Tooltip>
        <Tooltip title="滚动到今天">
          <Button size="small" icon={<HomeOutlined />} onClick={scrollToToday} />
        </Tooltip>
        <Tooltip title="回到起点">
          <Button size="small" icon={<ReloadOutlined />} onClick={() => hScrollRef.current?.scrollTo({ left: 0, behavior: 'smooth' })} />
        </Tooltip>
        <span style={{ fontSize: ds.metaFontSize, color: 'var(--cn-text-muted)' }}>
          {fmtDate(timeRange.min)} ~ {fmtDate(timeRange.max)}
        </span>
      </div>
    </div>
  )
}

// ── 左侧列 body —— 与右侧纵向滚动同步 ──────────────────

interface LeftColBodyProps {
  groupedTasks: Array<{
    key: string
    label: string
    tasks: GanttTask[]
    color: string
    index: number
  }>
  ds: ReturnType<typeof densityStyle>
  groupField: boolean
  onRowClick?: (r: RowResponse) => void
  rightScrollRef: React.RefObject<HTMLDivElement>
}

const LeftColBody = memo(function LeftColBody({ groupedTasks, ds, groupField, onRowClick, rightScrollRef }: LeftColBodyProps) {
  const leftRef = useRef<HTMLDivElement>(null)

  // 同步右侧 body 的纵向滚动 —— 用 MutationObserver 或直接 wheel 事件
  // 简单方案：监听左侧 wheel，转发到右侧；监听右侧 scroll，同步左侧
  useEffect(() => {
    const leftEl = leftRef.current
    const rightEl = rightScrollRef.current
    if (!leftEl || !rightEl) return

    // 找到右侧 body 里的纵向滚动容器（overflow: auto）
    const rightBody = rightEl.querySelector<HTMLDivElement>('div[style*="overflow: auto"]')
    if (!rightBody) return

    let syncing = false
    const onRightScroll = () => {
      if (syncing) return
      syncing = true
      leftEl.scrollTop = rightBody.scrollTop
      requestAnimationFrame(() => { syncing = false })
    }
    const onLeftScroll = () => {
      if (syncing) return
      syncing = true
      rightBody.scrollTop = leftEl.scrollTop
      requestAnimationFrame(() => { syncing = false })
    }
    rightBody.addEventListener('scroll', onRightScroll)
    leftEl.addEventListener('scroll', onLeftScroll)
    return () => {
      rightBody.removeEventListener('scroll', onRightScroll)
      leftEl.removeEventListener('scroll', onLeftScroll)
    }
  }, [rightScrollRef])

  return (
    <div
      ref={leftRef}
      style={{
        flex: 1,
        overflowY: 'auto',
        overflowX: 'hidden',
      }}
    >
      {groupedTasks.map((group) => (
        <div key={group.key}>
          {/* 分组 header —— 有 group_field 时显示，否则不显示（任务直接平铺） */}
          {groupField && (
            <div
              style={{
                height: ds.groupHeaderHeight,
                padding: '0 12px',
                background: `${group.color}15`,
                borderBottom: '1px solid var(--cn-border)',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontSize: ds.metaFontSize,
                fontWeight: 600,
                color: group.color,
                position: 'relative',
                flexShrink: 0,
              }}
            >
              {/* 左侧色条 */}
              <span
                style={{
                  width: 3,
                  height: 16,
                  borderRadius: 2,
                  background: group.color,
                  flexShrink: 0,
                }}
              />
              {/* WBS 组编号 */}
              <span
                style={{
                  fontSize: ds.metaFontSize - 1,
                  color: 'var(--cn-text-muted)',
                  fontWeight: 500,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                }}
              >
                G{group.index}
              </span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {group.label}
              </span>
              <span style={{ color: 'var(--cn-text-muted)', fontWeight: 400, marginLeft: 'auto' }}>
                ({group.tasks.length})
              </span>
            </div>
          )}

          {/* 任务行 —— 带树状连接线 */}
          {group.tasks.map((task, tIdx) => {
            const isLast = tIdx === group.tasks.length - 1
            return (
              <div
                key={task.row.id}
                onClick={() => onRowClick?.(task.row)}
                style={{
                  height: ds.rowHeight,
                  padding: '0 12px',
                  borderBottom: '1px solid var(--cn-border)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  position: 'relative',
                  gap: 8,
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--cn-bg-subtle)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = '' }}
              >
                {/* WBS 编号 */}
                <span
                  style={{
                    fontSize: ds.metaFontSize - 1,
                    color: 'var(--cn-text-muted)',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                    flexShrink: 0,
                    minWidth: groupField ? 36 : 28,
                  }}
                >
                  {groupField ? `G${group.index}.${tIdx + 1}` : `${tIdx + 1}`}
                </span>
                {/* 树状连接符 */}
                <span
                  style={{
                    color: 'var(--cn-text-muted)',
                    fontSize: ds.titleFontSize,
                    lineHeight: 1,
                    flexShrink: 0,
                    width: 10,
                    textAlign: 'center',
                  }}
                >
                  {groupField ? (isLast ? '└' : '├') : (tIdx === group.tasks.length - 1 ? '—' : '│')}
                </span>
                {/* 任务标题 */}
                <div
                  style={{
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    fontSize: ds.titleFontSize,
                    fontWeight: 500,
                  }}
                >
                  {task.title}
                </div>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
})

// ── 分组块（右侧 body 里的一组任务行 + 甘特条） ────────────

interface GroupBlockProps {
  group: {
    key: string
    label: string
    tasks: GanttTask[]
    color: string
    index: number
  }
  ds: ReturnType<typeof densityStyle>
  groupField: boolean
  timeRange: { min: Date; max: Date }
  pxPerDay: number
  totalTimelineWidth: number
  onRowClick?: (r: RowResponse) => void
}

const GroupBlock = memo(function GroupBlock({ group, ds, groupField, timeRange, pxPerDay, totalTimelineWidth, onRowClick }: GroupBlockProps) {
  return (
    <div style={{ position: 'relative', width: totalTimelineWidth, zIndex: 1 }}>
      {/* 分组 header 背景条 —— 与左侧高度一致 */}
      {groupField && (
        <div
          aria-hidden
          style={{
            height: ds.groupHeaderHeight,
            background: `${group.color}15`,
            borderBottom: '1px solid var(--cn-border)',
          }}
        />
      )}

      {/* 任务行 */}
      {group.tasks.map((task) => (
        <div
          key={task.row.id}
          onClick={() => onRowClick?.(task.row)}
          style={{
            height: ds.rowHeight,
            borderBottom: '1px solid var(--cn-border)',
            position: 'relative',
            background: 'var(--cn-bg-container)',
            cursor: 'pointer',
            transition: 'background 0.15s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--cn-bg-subtle)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = '' }}
        >
          <GanttBar
            task={task}
            range={timeRange}
            pxPerDay={pxPerDay}
            barHeight={ds.barHeight}
            onRowClick={onRowClick}
          />
        </div>
      ))}
    </div>
  )
})

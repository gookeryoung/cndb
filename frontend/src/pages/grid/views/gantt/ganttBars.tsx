/** 甘特条 / 今日标线 / 右边界虚线 —— 时间轴上的纯渲染组件. */

import { memo } from 'react'
import type { RowResponse } from '@/api'
import { fmtDate } from '../../cells/dateUtils'
import type { GanttTask } from '../ganttTimeline'
import { daysBetween } from '../ganttTimeline'
import { WEIGHT } from '@/theme/tokens'

export interface GanttBarProps {
  task: GanttTask
  range: { min: Date }
  pxPerDay: number
  barHeight: number
  onRowClick?: (r: RowResponse) => void
}

export const GanttBar = memo(function GanttBar({ task, range, pxPerDay, barHeight, onRowClick }: GanttBarProps) {
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
            fontWeight: WEIGHT.medium,
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

export function TodayLine({
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

// ── 时间轴右边界虚线 ──────────────────────────────────

/** 在时间轴最右端（range.max 位置）画一条虚线，标记"截至日期/时间范围边界"，
 *  覆盖 header 双层与 body grid 背景三处容器的右边界。
 *  虚线整体收在 totalWidth 内侧（left = totalWidth - 2）：若画在 totalWidth 处，
 *  2px 边框会向右扩展滚动溢出区，导致总宽恰好等于视口时也出现横向滚动条。 */
export function RightBoundaryLine({
  totalWidth,
  visible = true,
  label,
}: {
  /** 时间轴总宽度（= totalTimelineWidth） */
  totalWidth: number
  visible?: boolean
  /** 角标文本（可选，默认不显示） */
  label?: string
}) {
  if (!visible || totalWidth <= 0) return null
  return (
    <div
      data-testid="gantt-boundary-line"
      aria-hidden
      style={{
        position: 'absolute',
        left: totalWidth - 2,
        top: 0,
        bottom: 0,
        width: 0,
        borderLeft: '2px dashed var(--cn-text-muted, #bfbfbf)',
        zIndex: 3,
        pointerEvents: 'none',
      }}
    >
      {label && (
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: 2,
            fontSize: 10,
            color: 'var(--cn-text-muted, #999)',
            background: 'var(--cn-bg-container, #fff)',
            padding: '0 3px',
            borderRadius: 2,
            whiteSpace: 'nowrap',
            border: '1px solid var(--cn-border, #e8e8e8)',
            lineHeight: 1.4,
          }}
        >
          {label}
        </span>
      )}
    </div>
  )
}

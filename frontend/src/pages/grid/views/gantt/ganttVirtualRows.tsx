/** 右侧时间轴虚拟行：组背景条与任务行（absolute 定位于虚拟窗口坐标）. */

import { memo } from 'react'
import type { RowResponse } from '@/api'
import type { GanttTask } from '../ganttTimeline'
import { GanttBar } from '../gantt/ganttBars'

export interface VirtualGroupHeaderProps {
  top: number
  width: number
  height: number
  color: string
}

/** 右侧分组头：仅渲染背景条（文字信息在左列），高度与左列组头一致 */
export const VirtualGroupHeader = memo(function VirtualGroupHeader({ top, width, height, color }: VirtualGroupHeaderProps) {
  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width,
        height,
        transform: `translateY(${top}px)`,
        background: `${color}15`,
        borderBottom: '1px solid var(--cn-border)',
      }}
    />
  )
})

export interface VirtualTaskRowProps {
  task: GanttTask
  top: number
  height: number
  width: number
  timeRange: { min: Date; max: Date }
  pxPerDay: number
  barHeight: number
  onRowClick?: (r: RowResponse) => void
}

/** 右侧任务行：行底框 + 甘特条，absolute 定位于虚拟窗口坐标 */
export const VirtualTaskRow = memo(function VirtualTaskRow({
  task, top, height, width, timeRange, pxPerDay, barHeight, onRowClick,
}: VirtualTaskRowProps) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width,
        height,
        transform: `translateY(${top}px)`,
        borderBottom: '1px solid var(--cn-border)',
        background: 'var(--cn-bg-container)',
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onClick={() => onRowClick?.(task.row)}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--cn-bg-subtle)' }}
      onMouseLeave={(e) => { e.currentTarget.style.background = '' }}
    >
      <GanttBar
        task={task}
        range={timeRange}
        pxPerDay={pxPerDay}
        barHeight={barHeight}
        onRowClick={onRowClick}
      />
    </div>
  )
})

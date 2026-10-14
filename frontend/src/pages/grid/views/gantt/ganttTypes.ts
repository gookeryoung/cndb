/** 甘特图虚拟行的分组与扁平化类型（左右两栏共用同一序列）. */

import type { GanttTask } from '../ganttTimeline'

/** 分组聚合结构（左侧 WBS 头与右侧组背景条共用） */
export interface GanttGroup {
  key: string
  label: string
  tasks: GanttTask[]
  color: string
  index: number // 组序号（1-based，用于 WBS 编号）
}

/** 扁平化虚拟行：分组头或任务行，左右两栏按同一序列切片 */
export type GanttFlatItem =
  | { kind: 'group'; key: string; size: number; group: GanttGroup }
  | {
    kind: 'task'
    key: string
    size: number
    group: GanttGroup
    task: GanttTask
    tIndex: number
  }

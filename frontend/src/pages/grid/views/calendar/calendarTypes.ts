/** 日历视图共用类型：事件与密度样式. */

import type { RowResponse } from '@/api'

export interface CalendarEvent {
  row: RowResponse
  date: Date
  title: string
  groupValue?: string
  color?: string
  /** 是否匹配完成标志（与看板 done_field 语义一致） */
  isDone?: boolean
}

export interface DensityStyle {
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

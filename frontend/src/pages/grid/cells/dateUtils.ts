/** 日期处理工具 — 跨 KanbanView / CalendarView 共用.
 *
 * Grid 的日期字段有 date（YYYY-MM-DD）和 datetime（ISO / UTC 字符串）两种格式。
 * parseDate 统一截取前 10 字符（YYYY-MM-DD）再解析，加 `T00:00:00` 规避时区偏移。
 */

/** 解析任意日期值为 Date（只取 YYYY-MM-DD，加 T00:00:00 规避时区） */
export function parseDate(value: unknown): Date | null {
  if (!value) return null
  const str = String(value).slice(0, 10)
  const d = new Date(str + 'T00:00:00')
  return Number.isNaN(d.getTime()) ? null : d
}

/** 格式化 Date 为 YYYY-MM-DD */
export function fmtDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 计算距今天数（负数表示已逾期） */
export function daysFromToday(target: Date): number {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate())
  return Math.round((t.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

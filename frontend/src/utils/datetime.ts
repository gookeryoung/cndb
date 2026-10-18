/** 统一的日期时间展示口径. */

import dayjs from 'dayjs'

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
/** 超过这个跨度就回落到日期，避免「237 天前」这类读数没有信息量 */
const RELATIVE_LIMIT = 30 * DAY

/** 分钟级时间戳展示：`YYYY-MM-DD HH:mm`；空值渲染为空串.
 *
 * 原先 issues / changeRequests 的 4 个页面各自复制了一份完全相同的实现。
 */
export function formatDateTime(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : ''
}

/** 相对时间：`刚刚` / `5 分钟前` / `3 小时前` / `2 天前` / `YYYY-MM-DD`.
 *
 * 用于版本历史这类「越近越有意义」的列表；绝对时间放在 title 里做精确对照。
 * `now` 可注入，便于单测；无法解析的时间原样退回 {@link formatDateTime}。
 */
export function formatRelativeTime(value?: string | null, now?: number | Date): string {
  if (!value) return ''
  const target = dayjs(value)
  if (!target.isValid()) return ''
  const nowMs = now === undefined ? Date.now() : typeof now === 'number' ? now : now.getTime()
  const delta = nowMs - target.valueOf()
  const abs = Math.abs(delta)

  if (abs < MINUTE) return delta >= 0 ? '刚刚' : '即将'
  const suffix = delta >= 0 ? '前' : '后'
  if (abs < HOUR) return `${Math.floor(abs / MINUTE)} 分钟${suffix}`
  if (abs < DAY) return `${Math.floor(abs / HOUR)} 小时${suffix}`
  if (abs < RELATIVE_LIMIT) return `${Math.floor(abs / DAY)} 天${suffix}`
  return target.format('YYYY-MM-DD')
}

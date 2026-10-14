/** 统一的日期时间展示口径. */

import dayjs from 'dayjs'

/** 分钟级时间戳展示：`YYYY-MM-DD HH:mm`；空值渲染为空串.
 *
 * 原先 issues / changeRequests 的 4 个页面各自复制了一份完全相同的实现。
 */
export function formatDateTime(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : ''
}

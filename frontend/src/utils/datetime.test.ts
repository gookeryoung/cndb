import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'

import { formatDateTime, formatRelativeTime } from './datetime'

describe('formatDateTime', () => {
  it('按 YYYY-MM-DD HH:mm 渲染（截断秒）', () => {
    // 不带偏移量的 ISO 串按运行时时区解析：本地/CI(UTC) 渲染结果相同，
    // 断言不依赖运行机器的时区
    expect(formatDateTime('2026-10-14T19:08:40')).toBe('2026-10-14 19:08')
  })

  it('带偏移量的时间戳换算到运行时时区后再渲染', () => {
    // 期望值用 dayjs 同源现算（同 GridCell.test.tsx 口径）：
    // 写死绝对值在 Asia/Shanghai 本地通过、在 UTC 的 CI 上必然失败
    const iso = '2026-10-14T19:08:40+08:00'
    expect(formatDateTime(iso)).toBe(dayjs(iso).format('YYYY-MM-DD HH:mm'))
    expect(formatDateTime(iso)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
  })

  it('空值渲染为空串（null / undefined / 空串）', () => {
    expect(formatDateTime(undefined)).toBe('')
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime('')).toBe('')
  })
})

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

describe('formatRelativeTime', () => {
  // 基准时间用本地 ISO 串并显式注入 now，不依赖运行时时区
  const now = new Date('2026-10-18T12:00:00')
  const at = (s: string) => new Date(s).valueOf()

  it('一分钟内为「刚刚」', () => {
    expect(formatRelativeTime('2026-10-18T11:59:30', now)).toBe('刚刚')
    expect(formatRelativeTime('2026-10-18T12:00:00', now)).toBe('刚刚')
  })

  it('分钟 / 小时 / 天按整数向下取整', () => {
    expect(formatRelativeTime('2026-10-18T11:55:00', now)).toBe('5 分钟前')
    expect(formatRelativeTime('2026-10-18T09:00:00', now)).toBe('3 小时前')
    expect(formatRelativeTime('2026-10-16T12:00:00', now)).toBe('2 天前')
  })

  it('未来时间用「后」结尾', () => {
    expect(formatRelativeTime('2026-10-18T12:05:00', new Date(at('2026-10-18T12:00:00')))).toBe('5 分钟后')
    expect(formatRelativeTime('2026-10-18T12:00:10', now)).toBe('即将')
  })

  it('超过 30 天回落到日期，避免超大数字', () => {
    expect(formatRelativeTime('2026-08-01T12:00:00', now)).toBe('2026-08-01')
  })

  it('空值与非法值渲染为空串', () => {
    expect(formatRelativeTime(undefined, now)).toBe('')
    expect(formatRelativeTime(null, now)).toBe('')
    expect(formatRelativeTime('', now)).toBe('')
    expect(formatRelativeTime('not-a-date', now)).toBe('')
  })

  it('不传 now 时以当前时间为基准（刚写入的版本为「刚刚」）', () => {
    expect(formatRelativeTime(new Date().toISOString())).toBe('刚刚')
  })
})

/** dateUtils 单元测试 —— 日期解析/格式化/距今计算 */
import { describe, expect, it } from 'vitest'
import { daysFromToday, fmtDate, parseDate } from './dateUtils'

describe('parseDate', () => {
  it('date 字符串（YYYY-MM-DD）解析为当日零点', () => {
    expect(parseDate('2026-01-15')).toEqual(new Date(2026, 0, 15))
  })

  it('datetime 字符串（ISO / UTC）截取前 10 字符解析', () => {
    expect(parseDate('2026-03-08T14:30:00Z')).toEqual(new Date(2026, 2, 8))
    expect(parseDate('2026-03-08 14:30:00')).toEqual(new Date(2026, 2, 8))
  })

  it('非法日期字符串返回 null', () => {
    expect(parseDate('not-a-date')).toBeNull()
    expect(parseDate('2026-13-99')).toBeNull()
  })

  it('空值（null/undefined/空串/0/false）返回 null', () => {
    expect(parseDate(null)).toBeNull()
    expect(parseDate(undefined)).toBeNull()
    expect(parseDate('')).toBeNull()
    expect(parseDate(0)).toBeNull()
    expect(parseDate(false)).toBeNull()
  })

  it('数字 YYYYMMDD 不视为合法日期（截取后无法解析返回 null）', () => {
    expect(parseDate(20260115)).toBeNull()
  })
})

describe('fmtDate', () => {
  it('输出 YYYY-MM-DD 且月/日补零', () => {
    expect(fmtDate(new Date(2026, 0, 5))).toBe('2026-01-05')
    expect(fmtDate(new Date(2026, 11, 31))).toBe('2026-12-31')
    expect(fmtDate(new Date(2026, 2, 8))).toBe('2026-03-08')
  })
})

describe('daysFromToday', () => {
  it('未来日期返回正数', () => {
    const future = new Date()
    future.setDate(future.getDate() + 7)
    expect(daysFromToday(future)).toBe(7)
  })

  it('过去日期返回负数', () => {
    const past = new Date()
    past.setDate(past.getDate() - 3)
    expect(daysFromToday(past)).toBe(-3)
  })

  it('今天（含当天任意时刻）返回 0', () => {
    expect(daysFromToday(new Date())).toBe(0)
    const todayNight = new Date()
    todayNight.setHours(23, 59, 59)
    expect(daysFromToday(todayNight)).toBe(0)
  })
})

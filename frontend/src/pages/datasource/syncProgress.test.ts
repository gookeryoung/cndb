/** syncProgress 格式化工具单测（ADR 0040 判定层边界）.*/

import { describe, expect, it } from 'vitest'
import {
  RUNNING_ROWS_LIMIT,
  formatElapsed,
  formatRate,
  sortRunningJobs,
  visibleRunningJobs,
} from './syncProgress'

describe('formatElapsed', () => {
  it('毫秒为非正数或非有限值时输出 0 秒', () => {
    expect(formatElapsed(0)).toBe('0秒')
    expect(formatElapsed(-100)).toBe('0秒')
    expect(formatElapsed(Number.NaN)).toBe('0秒')
  })

  it('不足一分钟只显示秒', () => {
    expect(formatElapsed(1000)).toBe('1秒')
    expect(formatElapsed(59_900)).toBe('59秒')
  })

  it('超过一分钟显示分与秒', () => {
    expect(formatElapsed(60_000)).toBe('1分0秒')
    expect(formatElapsed(100_000)).toBe('1分40秒')
  })

  it('超过一小时显示小时与两位分钟', () => {
    expect(formatElapsed(3_660_000)).toBe('1小时01分')
  })
})

describe('formatRate', () => {
  it('无速度时输出 0 行/秒', () => {
    expect(formatRate(0)).toBe('0 行/秒')
    expect(formatRate(-1)).toBe('0 行/秒')
    expect(formatRate(Number.NaN)).toBe('0 行/秒')
  })

  it('千行以内保留一位小数', () => {
    expect(formatRate(12.34)).toBe('12.3 行/秒')
    expect(formatRate(0.1)).toBe('0.1 行/秒')
  })

  it('千行以上取整并加千分位', () => {
    expect(formatRate(16_480)).toBe('16,480 行/秒')
  })
})

describe('sortRunningJobs', () => {
  it('按开始时间倒序，同刻按任务 ID 倒序，空时间视为最早', () => {
    const jobs = [
      { id: 1, last_run_at: '2026-10-20T01:00:00Z' },
      { id: 3, last_run_at: null },
      { id: 4, last_run_at: '2026-10-20T03:00:00Z' },
      { id: 2, last_run_at: '2026-10-20T03:00:00Z' },
    ]
    expect(sortRunningJobs(jobs).map(job => job.id)).toEqual([4, 2, 1, 3])
  })

  it('不修改入参数组', () => {
    const jobs = [
      { id: 1, last_run_at: '2026-10-20T01:00:00Z' },
      { id: 2, last_run_at: '2026-10-20T02:00:00Z' },
    ]
    sortRunningJobs(jobs)
    expect(jobs.map(job => job.id)).toEqual([1, 2])
  })
})

describe('visibleRunningJobs', () => {
  const jobs = Array.from({ length: 7 }, (_, index) => ({
    id: index + 1,
    last_run_at: `2026-10-20T0${index}:00:00Z`,
  }))

  it('不超过常显上限时全部展示', () => {
    expect(visibleRunningJobs(jobs.slice(0, RUNNING_ROWS_LIMIT), false)).toEqual({
      visible: jobs.slice(0, RUNNING_ROWS_LIMIT).reverse(),
      hidden: 0,
    })
  })

  it('超过上限时截断并给出折叠数量', () => {
    const result = visibleRunningJobs(jobs, false)
    expect(result.visible).toHaveLength(RUNNING_ROWS_LIMIT)
    expect(result.visible.map(job => job.id)).toEqual([7, 6, 5, 4, 3])
    expect(result.hidden).toBe(2)
  })

  it('展开后全量展示且不再折叠', () => {
    const result = visibleRunningJobs(jobs, true)
    expect(result.visible).toHaveLength(7)
    expect(result.visible.map(job => job.id)).toEqual([7, 6, 5, 4, 3, 2, 1])
    expect(result.hidden).toBe(0)
  })
})

/** syncProgress 格式化工具单测（ADR 0040 判定层边界）.*/

import { describe, expect, it } from 'vitest'
import { formatElapsed, formatRate } from './syncProgress'

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

import { describe, expect, it } from 'vitest'

import { formatSize } from './formatSize'

describe('formatSize', () => {
  it('小于 1KB 输出 B', () => {
    expect(formatSize(0)).toBe('0 B')
    expect(formatSize(1023)).toBe('1023 B')
  })

  it('小于 1MB 输出 KB（默认 1 位小数）', () => {
    expect(formatSize(1024)).toBe('1.0 KB')
    expect(formatSize(1536)).toBe('1.5 KB')
  })

  it('大于等于 1MB 输出 MB', () => {
    expect(formatSize(1024 * 1024)).toBe('1.0 MB')
    expect(formatSize(3 * 1024 * 1024)).toBe('3.0 MB')
  })

  it('fractionDigits 同时作用于 KB 与 MB（管理面板用 2 位）', () => {
    expect(formatSize(1536, 2)).toBe('1.50 KB')
    expect(formatSize(1024 * 1024, 2)).toBe('1.00 MB')
  })
})

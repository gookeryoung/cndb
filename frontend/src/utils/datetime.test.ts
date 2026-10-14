import { describe, expect, it } from 'vitest'

import { formatDateTime } from './datetime'

describe('formatDateTime', () => {
  it('按 YYYY-MM-DD HH:mm 渲染', () => {
    expect(formatDateTime('2026-10-14T19:08:40+08:00')).toBe('2026-10-14 19:08')
  })

  it('空值渲染为空串（null / undefined / 空串）', () => {
    expect(formatDateTime(undefined)).toBe('')
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime('')).toBe('')
  })
})

/** 内容区滚动位置记忆（sessionStorage）测试. */

import { describe, expect, it } from 'vitest'
import { readScrollTop, SCROLL_STORAGE_KEY, writeScrollTop } from './scrollMemory'

describe('scrollMemory', () => {
  it('写入后按路径读回滚动位置', () => {
    writeScrollTop('/w/10/tables', 320)
    writeScrollTop('/w/10/documents', 120)

    expect(readScrollTop('/w/10/tables')).toBe(320)
    expect(readScrollTop('/w/10/documents')).toBe(120)
  })

  it('写入 0 视为清除（回到顶部不留脏记录）', () => {
    writeScrollTop('/w/10/tables', 320)
    writeScrollTop('/w/10/tables', 0)
    expect(readScrollTop('/w/10/tables')).toBe(0)
  })

  it('未记录或数据损坏时回落 0', () => {
    expect(readScrollTop('/never')).toBe(0)
    sessionStorage.setItem(SCROLL_STORAGE_KEY, '{broken')
    expect(readScrollTop('/never')).toBe(0)
  })

  it('最多保留 50 条，超出后丢弃最早记录', () => {
    for (let i = 0; i < 55; i += 1) writeScrollTop(`/p/${i}`, i + 1)
    const stored = JSON.parse(sessionStorage.getItem(SCROLL_STORAGE_KEY) ?? '{}') as Record<string, number>
    expect(Object.keys(stored)).toHaveLength(50)
    expect(readScrollTop('/p/0')).toBe(0)
    expect(readScrollTop('/p/54')).toBe(55)
  })
})

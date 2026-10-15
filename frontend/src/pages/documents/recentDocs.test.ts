/** recentDocs 测试 —— 本地最近打开记录（去重 / 上限 / 损坏兜底 / 按工作区隔离）. */

import { afterEach, describe, expect, it } from 'vitest'

import {
  RECENT_DOCS_LIMIT,
  clearRecentDocs,
  loadRecentDocs,
  pushRecentDoc,
} from './recentDocs'

afterEach(() => {
  window.localStorage.clear()
})

describe('recentDocs', () => {
  it('新打开置顶，重复打开只保留最新一条', () => {
    pushRecentDoc(10, { id: 1, title: '甲' }, 1000)
    pushRecentDoc(10, { id: 2, title: '乙' }, 2000)
    pushRecentDoc(10, { id: 1, title: '甲', }, 3000)

    const list = loadRecentDocs(10)
    expect(list.map(i => i.id)).toEqual([1, 2])
    expect(list[0].at).toBe(3000)
  })

  it(`最多保留 ${RECENT_DOCS_LIMIT} 条（超出丢弃最旧）`, () => {
    for (let i = 1; i <= RECENT_DOCS_LIMIT + 3; i++) pushRecentDoc(10, { id: i, title: `文档${i}` }, i)
    const list = loadRecentDocs(10)
    expect(list).toHaveLength(RECENT_DOCS_LIMIT)
    expect(list[0].id).toBe(RECENT_DOCS_LIMIT + 3)
    expect(list.map(i => i.id)).not.toContain(1)
  })

  it('按工作区隔离，互不影响', () => {
    pushRecentDoc(10, { id: 1, title: '甲' }, 1000)
    pushRecentDoc(20, { id: 9, title: '乙' }, 2000)

    expect(loadRecentDocs(10).map(i => i.id)).toEqual([1])
    expect(loadRecentDocs(20).map(i => i.id)).toEqual([9])
  })

  it('未记录过时返回空数组', () => {
    expect(loadRecentDocs(99)).toEqual([])
  })

  it('数据损坏（非 JSON / 非数组 / 缺字段）时安全退化', () => {
    window.localStorage.setItem('cndb_recent_docs_v1:10', '{not json')
    expect(loadRecentDocs(10)).toEqual([])

    window.localStorage.setItem('cndb_recent_docs_v1:10', JSON.stringify({ a: 1 }))
    expect(loadRecentDocs(10)).toEqual([])

    window.localStorage.setItem('cndb_recent_docs_v1:10', JSON.stringify([
      { id: 1, title: 'ok', at: 1 },
      { id: 'bad', title: 'x', at: 2 },
      { title: 'missing id', at: 3 },
    ]))
    expect(loadRecentDocs(10).map(i => i.id)).toEqual([1])
  })

  it('clearRecentDocs 清空当前工作区', () => {
    pushRecentDoc(10, { id: 1, title: '甲' })
    pushRecentDoc(20, { id: 2, title: '乙' })

    clearRecentDocs(10)
    expect(loadRecentDocs(10)).toEqual([])
    expect(loadRecentDocs(20)).toHaveLength(1)
  })
})

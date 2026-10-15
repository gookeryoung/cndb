/** documentSort 纯函数测试 —— 置顶优先 + 四种排序口径. */

import { describe, expect, it } from 'vitest'

import { DOCUMENT_ORDER_OPTIONS, sortDocuments, type SortableDocument } from './documentSort'

const docs: SortableDocument[] = [
  { title: 'Banana', sort_order: 0, updated_at: '2026-01-01T00:00:00Z', created_at: '2025-01-01T00:00:00Z' },
  { title: 'apple', sort_order: 1, updated_at: '2026-03-01T00:00:00Z', created_at: '2025-06-01T00:00:00Z' },
  { title: 'Cherry', sort_order: 2, updated_at: '2026-02-01T00:00:00Z', created_at: '2025-03-01T00:00:00Z' },
]

describe('sortDocuments', () => {
  it('sort 口径保持传入顺序（手动顺序由后端排定）', () => {
    expect(sortDocuments(docs, 'sort').map(d => d.title)).toEqual(['Banana', 'apple', 'Cherry'])
  })

  it('updated 口径按更新时间倒序', () => {
    expect(sortDocuments(docs, 'updated').map(d => d.title)).toEqual(['apple', 'Cherry', 'Banana'])
  })

  it('created 口径按创建时间倒序', () => {
    expect(sortDocuments(docs, 'created').map(d => d.title)).toEqual(['apple', 'Cherry', 'Banana'])
  })

  it('title 口径按中文/字母表顺序（忽略大小写）', () => {
    expect(sortDocuments(docs, 'title').map(d => d.title)).toEqual(['apple', 'Banana', 'Cherry'])
  })

  it('置顶项在所有口径下都排最前', () => {
    const withPinned = docs.map(d => ({ ...d, pinned: d.title === 'Cherry' }))
    for (const order of ['sort', 'updated', 'created', 'title'] as const) {
      expect(sortDocuments(withPinned, order)[0]!.title).toBe('Cherry')
    }
  })

  it('中文标题按拼音顺序、数字按键值感知排序', () => {
    const zh = [{ title: '文档 10' }, { title: '文档 2' }, { title: '阿' }]
    expect(sortDocuments(zh, 'title').map(d => d.title)).toEqual(['阿', '文档 2', '文档 10'])
  })

  it('缺失或非法时间视为最旧（排在最后）', () => {
    const items = [
      { title: 'none' },
      { title: 'bad', updated_at: 'not-a-date' },
      { title: 'ok', updated_at: '2026-01-01T00:00:00Z' },
    ]
    expect(sortDocuments(items, 'updated').map(d => d.title)[0]).toBe('ok')
    expect(sortDocuments(items, 'updated').map(d => d.title).slice(1)).toEqual(
      expect.arrayContaining(['none', 'bad']),
    )
  })

  it('不修改传入数组（返回新数组）', () => {
    const input = [...docs]
    sortDocuments(input, 'title')
    expect(input.map(d => d.title)).toEqual(['Banana', 'apple', 'Cherry'])
  })

  it('选项清单包含四种口径', () => {
    expect(DOCUMENT_ORDER_OPTIONS.map(o => o.value)).toEqual(['sort', 'updated', 'created', 'title'])
  })
})

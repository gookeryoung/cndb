import { describe, expect, it } from 'vitest'
import type { DashboardQuery } from './dashboardModel'
import { hasGlobalRef, resolveGlobalValue, resolveQueryGlobals } from './dashboardGlobals'

function query(filters: DashboardQuery['filters']): DashboardQuery {
  return { filters, filter_logic: 'AND', sortings: [] }
}

describe('dashboardGlobals', () => {
  it('识别占位符（字符串 / 数组）', () => {
    expect(hasGlobalRef('{{global.range}}')).toBe(true)
    expect(hasGlobalRef(['{{global.range}}', '2026-02-01'])).toBe(true)
    expect(hasGlobalRef('数码')).toBe(false)
    expect(hasGlobalRef(123)).toBe(false)
  })

  it('date_range 的 {from,to} 转二元数组', () => {
    const [value, ok] = resolveGlobalValue('{{global.range}}', {
      range: { from: '2026-01-01', to: '2026-01-31' },
    })
    expect(ok).toBe(true)
    expect(value).toEqual(['2026-01-01', '2026-01-31'])
  })

  it('select 数组与 search 字符串原样注入', () => {
    const [list, okList] = resolveGlobalValue('{{global.cat}}', { cat: ['数码', '家电'] })
    expect(okList).toBe(true)
    expect(list).toEqual(['数码', '家电'])
    const [text, okText] = resolveGlobalValue('{{global.keyword}}', { keyword: 'A00' })
    expect(okText).toBe(true)
    expect(text).toBe('A00')
  })

  it('缺值条件丢弃并计数，未引用的条件保留', () => {
    const result = resolveQueryGlobals(
      query([
        { field_name: '日期', op: 'date_range', value: '{{global.range}}' },
        { field_name: '商品类别', op: 'eq', value: '数码' },
      ]),
      {},
    )
    expect(result.unapplied).toBe(1)
    expect(result.query.filters).toEqual([{ field_name: '商品类别', op: 'eq', value: '数码' }])
  })

  it('数组里任一占位符缺值则整条丢弃', () => {
    const result = resolveQueryGlobals(
      query([{ field_name: '日期', op: 'between', value: ['{{global.from}}', '{{global.to}}'] }]),
      { from: '2026-01-01' },
    )
    expect(result.unapplied).toBe(1)
    expect(result.query.filters).toEqual([])
  })

  it('无 filters 时原样返回', () => {
    const original = query([])
    const result = resolveQueryGlobals(original, { range: [] })
    expect(result.query).toBe(original)
    expect(result.unapplied).toBe(0)
  })
})

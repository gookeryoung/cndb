/** dashboard 客户端组件级查询单元测试（过滤 / 排序 / 截断）. */
import { describe, expect, it } from 'vitest'
import type { RowResponse } from '@/api'
import { applyWidgetQuery } from './dashboardQuery'
import type { DashboardQuery } from './dashboardModel'

const rows: RowResponse[] = [
  { id: 1, 类别: 'A', 金额: 10, 日期: '2026-01-05' },
  { id: 2, 类别: 'B', 金额: 30, 日期: '2026-02-10' },
  { id: 3, 类别: 'A', 金额: 20, 日期: '2026-03-20' },
  { id: 4, 类别: null, 金额: null, 日期: null },
] as unknown as RowResponse[]

const q = (patch: Partial<DashboardQuery>): DashboardQuery => ({
  filters: [], filter_logic: 'AND', sortings: [], ...patch,
})

describe('applyWidgetQuery — filters', () => {
  it('数值比较操作符', () => {
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '金额', op: '>=', value: 20 }] })).map((r) => r.id))
      .toEqual([2, 3])
  })

  it('文本 equals / contains', () => {
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '类别', op: 'eq', value: 'A' }] })).map((r) => r.id))
      .toEqual([1, 3])
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '类别', op: 'contains', value: 'B' }] })).map((r) => r.id))
      .toEqual([2])
  })

  it('in / not_in', () => {
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '类别', op: 'in', value: ['A', 'B'] }] })).map((r) => r.id))
      .toEqual([1, 2, 3])
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '类别', op: 'not_in', value: ['A'] }] })).map((r) => r.id))
      .toEqual([2, 4])
  })

  it('空值判断', () => {
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '金额', op: 'is_empty', value: null }] })).map((r) => r.id))
      .toEqual([4])
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '金额', op: 'is_not_empty', value: null }] })).map((r) => r.id))
      .toEqual([1, 2, 3])
  })

  it('between / date_range 闭区间', () => {
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '金额', op: 'between', value: [10, 20] }] })).map((r) => r.id))
      .toEqual([1, 3])
    expect(applyWidgetQuery(rows, q({ filters: [{ field_name: '日期', op: 'date_range', value: ['2026-01-01', '2026-02-28'] }] })).map((r) => r.id))
      .toEqual([1, 2])
  })

  it('AND / OR 组合', () => {
    const filters = [
      { field_name: '类别', op: 'eq', value: 'A' },
      { field_name: '金额', op: '>', value: 15 },
    ]
    expect(applyWidgetQuery(rows, q({ filters, filter_logic: 'AND' })).map((r) => r.id)).toEqual([3])
    expect(applyWidgetQuery(rows, q({ filters, filter_logic: 'OR' })).map((r) => r.id)).toEqual([1, 2, 3])
  })
})

describe('applyWidgetQuery — sortings / limit', () => {
  it('多字段排序，空值恒排后', () => {
    const out = applyWidgetQuery(rows, q({ sortings: [
      { field_name: '类别', direction: 'desc' },
      { field_name: '金额', direction: 'desc' },
    ] }))
    expect(out.map((r) => r.id)).toEqual([2, 3, 1, 4])
  })

  it('limit 截断', () => {
    expect(applyWidgetQuery(rows, q({ sortings: [{ field_name: '金额', direction: 'asc' }], limit: 2 })).map((r) => r.id))
      .toEqual([1, 3])
  })
})

describe('applyWidgetQuery — 入参不可变', () => {
  it('排序不修改原始 rows', () => {
    const before = rows.map((r) => r.id)
    applyWidgetQuery(rows, q({ sortings: [{ field_name: '金额', direction: 'desc' }] }))
    expect(rows.map((r) => r.id)).toEqual(before)
  })
})

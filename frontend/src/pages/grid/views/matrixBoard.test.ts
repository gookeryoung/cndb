/**
 * matrixBoard 纯逻辑层测试 —— 矩阵视图二维分组.
 *
 * 覆盖：日期分桶（五种粒度 + 空值/非法值）/ 轴 key 类型分派 /
 * 轴排序（日期时序、分类 zh-CN、「未分组」恒最后）/ 网格构建归属与计数。
 */

import { describe, expect, it } from 'vitest'
import type { Field, RowResponse } from '@/api'
import { makeField } from '@/test/fixtures'
import {
  UNGROUPED_LABEL,
  axisKeyForRow,
  buildMatrixGrid,
  bucketTitle,
  cellKey,
  dateBucket,
  sortAxisKeys,
} from './matrixBoard'

describe('dateBucket 日期分桶', () => {
  it('五种粒度产出字典序==时序的桶 key', () => {
    const v = '2026-09-15'
    expect(dateBucket(v, 'year')).toBe('2026')
    expect(dateBucket(v, 'quarter')).toBe('2026-Q3')
    expect(dateBucket(v, 'month')).toBe('2026-09')
    expect(dateBucket(v, 'day')).toBe('2026-09-15')
    // week 取该周起始日
    expect(dateBucket(v, 'week')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('空值与非法值返回空串（归未分组）', () => {
    expect(dateBucket(null, 'month')).toBe('')
    expect(dateBucket(undefined, 'month')).toBe('')
    expect(dateBucket('', 'month')).toBe('')
    expect(dateBucket('not-a-date', 'month')).toBe('')
  })

  it('跨季度日期正确落桶', () => {
    expect(dateBucket('2026-01-02', 'quarter')).toBe('2026-Q1')
    expect(dateBucket('2026-12-31', 'quarter')).toBe('2026-Q4')
  })
})

describe('bucketTitle 轴头标题', () => {
  it('week 粒度补充「当周」后缀，未分组与其余粒度原样', () => {
    expect(bucketTitle('2026-09-14', 'week')).toBe('2026-09-14 当周')
    expect(bucketTitle('2026-09-15', 'day')).toBe('2026-09-15')
    expect(bucketTitle('2026-09', 'month')).toBe('2026-09')
    expect(bucketTitle(UNGROUPED_LABEL, 'week')).toBe(UNGROUPED_LABEL)
  })
})

describe('axisKeyForRow 轴 key 求值', () => {
  const selectField = makeField({ id: 2, name: '团队', field_type: 'select', config: { options: ['研发组', '设计组'] } })
  const linkField = makeField({ id: 3, name: '关联课题', field_type: 'link' })
  const multiField = makeField({ id: 4, name: '标签', field_type: 'multi_select', config: { options: ['紧急', '常规'] } })
  const dateField = makeField({ id: 5, name: '排期日期', field_type: 'date' })
  const textField = makeField({ id: 6, name: '负责人', field_type: 'text' })

  it('select 取 options 标签', () => {
    expect(axisKeyForRow({ id: 1, 团队: '研发组' } as unknown as RowResponse, selectField, 'month')).toBe('研发组')
  })

  it('link 取首值标签', () => {
    expect(axisKeyForRow({ id: 1, 关联课题: [{ label: '课题A' }] } as unknown as RowResponse, linkField, 'month')).toBe('课题A')
  })

  it('multi_select 取首值标签', () => {
    expect(axisKeyForRow({ id: 1, 标签: ['紧急', '常规'] } as unknown as RowResponse, multiField, 'month')).toBe('紧急')
  })

  it('date 按粒度分桶', () => {
    expect(axisKeyForRow({ id: 1, 排期日期: '2026-09-15' } as unknown as RowResponse, dateField, 'month')).toBe('2026-09')
    expect(axisKeyForRow({ id: 1, 排期日期: '2026-09-15' } as unknown as RowResponse, dateField, 'year')).toBe('2026')
  })

  it('text 与未知类型 String 化；空值返回空串', () => {
    expect(axisKeyForRow({ id: 1, 负责人: '陈立' } as unknown as RowResponse, textField, 'month')).toBe('陈立')
    expect(axisKeyForRow({ id: 1, 负责人: null } as unknown as RowResponse, textField, 'month')).toBe('')
    expect(axisKeyForRow({} as unknown as RowResponse, undefined, 'month')).toBe('')
  })
})

describe('sortAxisKeys 轴排序', () => {
  it('日期轴按字典序（==时序）', () => {
    expect(sortAxisKeys(['2026-09', '2026-07', '2026-08'], true)).toEqual(['2026-07', '2026-08', '2026-09'])
  })

  it('「未分组」恒排在末尾', () => {
    expect(sortAxisKeys([UNGROUPED_LABEL, '2026-07', '2026-08'], true)).toEqual(['2026-07', '2026-08', UNGROUPED_LABEL])
    expect(sortAxisKeys(['研发组', UNGROUPED_LABEL, '测试组'], false)).toEqual(['测试组', '研发组', UNGROUPED_LABEL])
  })

  it('分类轴按 zh-CN localeCompare', () => {
    const keys = sortAxisKeys(['设计组', '研发组', '测试组', '实施组'], false)
    expect(keys).toEqual([...keys].sort((a, b) => a.localeCompare(b, 'zh-CN')))
  })
})

describe('buildMatrixGrid 网格构建', () => {
  const FIELDS: Field[] = [
    makeField({ id: 1, name: '团队', field_type: 'select', config: { options: ['研发组', '设计组', '测试组'] } }),
    makeField({ id: 2, name: '排期日期', field_type: 'date' }),
  ]
  const ROWS: RowResponse[] = [
    { id: 1, 团队: '研发组', 排期日期: '2026-07-06' },
    { id: 2, 团队: '研发组', 排期日期: '2026-08-10' },
    { id: 3, 团队: '测试组', 排期日期: '2026-07-09' },
    { id: 4, 团队: '设计组', 排期日期: null },
    { id: 5, 团队: null, 排期日期: '2026-07-20' },
  ] as unknown as RowResponse[]

  it('二维归属：行按（纵轴×横轴）分格，空值归未分组', () => {
    const grid = buildMatrixGrid(ROWS, FIELDS, '团队', '排期日期', 'month')
    expect(grid.rowKeys).toEqual(['研发组', '测试组', '设计组', UNGROUPED_LABEL].sort((a, b) =>
      a === UNGROUPED_LABEL ? 1 : b === UNGROUPED_LABEL ? -1 : a.localeCompare(b, 'zh-CN'),
    ))
    expect(grid.columnKeys).toEqual(['2026-07', '2026-08', UNGROUPED_LABEL])
    expect(grid.cells.get(cellKey('研发组', '2026-07'))!.map((r) => r.id)).toEqual([1])
    expect(grid.cells.get(cellKey('研发组', '2026-08'))!.map((r) => r.id)).toEqual([2])
    expect(grid.cells.get(cellKey('测试组', '2026-07'))!.map((r) => r.id)).toEqual([3])
    // 设计组无日期 → 列「未分组」
    expect(grid.cells.get(cellKey('设计组', UNGROUPED_LABEL))!.map((r) => r.id)).toEqual([4])
    // 无团队 → 行「未分组」
    expect(grid.cells.get(cellKey(UNGROUPED_LABEL, '2026-07'))!.map((r) => r.id)).toEqual([5])
  })

  it('同一单元格多行保持 API 返回顺序', () => {
    const extra: RowResponse = { id: 6, 团队: '研发组', 排期日期: '2026-07-08' } as unknown as RowResponse
    const grid2 = buildMatrixGrid([...ROWS, extra], FIELDS, '团队', '排期日期', 'month')
    expect(grid2.cells.get(cellKey('研发组', '2026-07'))!.map((r) => r.id)).toEqual([1, 6])
  })

  it('日期轴 year 粒度合并月份桶', () => {
    const grid = buildMatrixGrid(ROWS, FIELDS, '团队', '排期日期', 'year')
    expect(grid.columnKeys).toEqual(['2026', UNGROUPED_LABEL])
    expect(grid.cells.get(cellKey('研发组', '2026'))!.map((r) => r.id)).toEqual([1, 2])
  })

  it('空行集合产出空网格', () => {
    const grid = buildMatrixGrid([], FIELDS, '团队', '排期日期', 'month')
    expect(grid.rowKeys).toEqual([])
    expect(grid.columnKeys).toEqual([])
    expect(grid.cells.size).toBe(0)
  })
})

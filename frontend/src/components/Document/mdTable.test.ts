/** mdTable 解析 — 实时预览把表格源码还原成行列结构 */

import { describe, expect, it } from 'vitest'
import { parseMdTable, splitTableRow } from './mdTable'

describe('splitTableRow', () => {
  it('去掉外侧竖线产生的空单元并 trim', () => {
    expect(splitTableRow('| a | b |')).toEqual(['a', 'b'])
  })

  it('允许省略外侧竖线', () => {
    expect(splitTableRow('a | b')).toEqual(['a', 'b'])
  })

  it('保留空单元（中间列留空）', () => {
    expect(splitTableRow('| a |  | c |')).toEqual(['a', '', 'c'])
  })

  it('转义的 \\| 不当作分隔符', () => {
    expect(splitTableRow('| a\\|b | c |')).toEqual(['a|b', 'c'])
  })
})

describe('parseMdTable', () => {
  it('解析表头 / 对齐 / 数据行', () => {
    const table = parseMdTable('| 名称 | 数量 |\n| :-- | --: |\n| 苹果 | 3 |\n| 梨 | 12 |')
    expect(table).not.toBeNull()
    expect(table!.header).toEqual(['名称', '数量'])
    expect(table!.align).toEqual(['left', 'right'])
    expect(table!.rows).toEqual([
      ['苹果', '3'],
      ['梨', '12'],
    ])
  })

  it('居中用 :-: 表示', () => {
    expect(parseMdTable('| a |\n| :-: |\n| 1 |')!.align).toEqual(['center'])
  })

  it('数据行多出的单元格截断，缺少的补空', () => {
    const table = parseMdTable('| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n| 4 |')
    expect(table!.rows).toEqual([
      ['1', '2'],
      ['4', ''],
    ])
  })

  it('对齐列数不足时补 null', () => {
    expect(parseMdTable('| a | b |\n| :-- |\n| 1 | 2 |')!.align).toEqual(['left', null])
  })

  it('不是表格返回 null', () => {
    expect(parseMdTable('| a | b |')).toBeNull()
    expect(parseMdTable('普通段落\n第二行')).toBeNull()
    expect(parseMdTable('| a |\n| x |')).toBeNull()
  })
})

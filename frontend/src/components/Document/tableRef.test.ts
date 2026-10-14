/** 数据表动态引用占位语法解析测试 — 纯函数覆盖：合法解析/参数钳制/非法回退/段落切片. */

import { describe, expect, it } from 'vitest'
import {
  DEFAULT_TABLE_REF_LIMIT,
  MAX_TABLE_REF_LIMIT,
  parseTableRef,
  splitTableRefs,
} from './tableRef'

describe('parseTableRef', () => {
  it('解析基本形式 {{table:<id>}}，limit 取默认值', () => {
    expect(parseTableRef('{{table:100}}')).toEqual({
      tableId: 100,
      limit: DEFAULT_TABLE_REF_LIMIT,
    })
  })

  it('解析 view 与 limit 参数', () => {
    expect(parseTableRef('{{table:100|view=200|limit=5}}')).toEqual({
      tableId: 100,
      view: 200,
      limit: 5,
    })
  })

  it('limit 超上限钳制为 50', () => {
    expect(parseTableRef('{{table:100|limit=999}}')?.limit).toBe(MAX_TABLE_REF_LIMIT)
  })

  it('limit 非法（0/负数/非数字）回退默认值', () => {
    expect(parseTableRef('{{table:100|limit=0}}')?.limit).toBe(DEFAULT_TABLE_REF_LIMIT)
    expect(parseTableRef('{{table:100|limit=-5}}')?.limit).toBe(DEFAULT_TABLE_REF_LIMIT)
    expect(parseTableRef('{{table:100|limit=abc}}')?.limit).toBe(DEFAULT_TABLE_REF_LIMIT)
  })

  it('limit 小数向下取整', () => {
    expect(parseTableRef('{{table:100|limit=10.7}}')?.limit).toBe(10)
  })

  it('view 非数字忽略；未知参数键忽略', () => {
    expect(parseTableRef('{{table:100|view=abc|foo=bar}}')).toEqual({
      tableId: 100,
      limit: DEFAULT_TABLE_REF_LIMIT,
    })
  })

  it('段内首尾空白容忍', () => {
    expect(parseTableRef('  {{table:7}}  ')).toEqual({
      tableId: 7,
      limit: DEFAULT_TABLE_REF_LIMIT,
    })
  })

  it('非法输入返回 null：混排文本/非数字表 ID/空串', () => {
    expect(parseTableRef('前文 {{table:100}}')).toBeNull()
    expect(parseTableRef('{{table:100}} 后文')).toBeNull()
    expect(parseTableRef('{{table:abc}}')).toBeNull()
    expect(parseTableRef('{{table:}}')).toBeNull()
    expect(parseTableRef('')).toBeNull()
    expect(parseTableRef('{{table:100')).toBeNull()
  })
})

describe('splitTableRefs', () => {
  it('空内容返回空数组', () => {
    expect(splitTableRefs('')).toEqual([])
  })

  it('无占位符：整体为单一 md 片段且文本原样保留', () => {
    const text = '# 标题\n\n正文段落。\n'
    expect(splitTableRefs(text)).toEqual([{ type: 'md', text }])
  })

  it('混合内容切为 md / table / md 三片段，前段保留段落分隔符', () => {
    const segments = splitTableRefs('# 标题\n\n{{table:100}}\n\n正文。\n')
    expect(segments).toHaveLength(3)
    expect(segments[0]).toEqual({ type: 'md', text: '# 标题\n\n' })
    expect(segments[1]).toEqual({ type: 'table', ref: { tableId: 100, limit: 20 } })
    expect(segments[2]).toEqual({ type: 'md', text: '正文。\n' })
  })

  it('占位符与文字同段不解析（行内混排按普通文本处理）', () => {
    const text = '说明文字 {{table:100}} 更多文字'
    expect(splitTableRefs(text)).toEqual([{ type: 'md', text }])
  })

  it('连续两个引用各自独立成片段', () => {
    const segments = splitTableRefs('{{table:100|limit=5}}\n\n{{table:101|view=9}}')
    expect(segments.map(s => s.type)).toEqual(['table', 'table'])
    expect(segments[0]).toEqual({ type: 'table', ref: { tableId: 100, limit: 5 } })
    expect(segments[1]).toEqual({ type: 'table', ref: { tableId: 101, view: 9, limit: 20 } })
  })

  it('md 片段文本保留：前段含分隔符，后段不含被引用吞掉的空行', () => {
    const segments = splitTableRefs('前文\n\n{{table:100}}\n\n后文')
    const mdTexts = segments.filter(s => s.type === 'md').map(s => (s as { text: string }).text)
    expect(mdTexts).toEqual(['前文\n\n', '后文'])
  })
})

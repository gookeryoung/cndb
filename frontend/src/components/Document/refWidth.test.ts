/** 引用宽度（ADR 0051）纯函数测试：解析回退 / 按出现序号改写 width / 保留其他参数. */

import { describe, expect, it } from 'vitest'
import {
  DEFAULT_REF_WIDTH,
  MAX_REF_WIDTH,
  MIN_REF_WIDTH,
  parseRefWidth,
  rewriteRefWidth,
} from './refWidth'

describe('parseRefWidth', () => {
  it('缺省 / 空串回退默认 75', () => {
    expect(parseRefWidth(undefined)).toBe(DEFAULT_REF_WIDTH)
    expect(parseRefWidth(null)).toBe(DEFAULT_REF_WIDTH)
    expect(parseRefWidth('')).toBe(DEFAULT_REF_WIDTH)
    expect(parseRefWidth('abc')).toBe(DEFAULT_REF_WIDTH)
  })

  it('非整数 / 越界回退默认 75', () => {
    expect(parseRefWidth('50.5')).toBe(DEFAULT_REF_WIDTH)
    expect(parseRefWidth(MIN_REF_WIDTH - 1)).toBe(DEFAULT_REF_WIDTH)
    expect(parseRefWidth(MAX_REF_WIDTH + 1)).toBe(DEFAULT_REF_WIDTH)
  })

  it('边界与合法整数原样返回', () => {
    expect(parseRefWidth(MIN_REF_WIDTH)).toBe(MIN_REF_WIDTH)
    expect(parseRefWidth(MAX_REF_WIDTH)).toBe(MAX_REF_WIDTH)
    expect(parseRefWidth('50')).toBe(50)
    expect(parseRefWidth(75)).toBe(75)
  })
})

describe('rewriteRefWidth', () => {
  it('无 width 时追加，图表与表格语法均支持', () => {
    expect(rewriteRefWidth('{{chart:300}}', { kind: 'chart', id: 300, occurrence: 0, width: 50 }))
      .toBe('{{chart:300|width=50}}')
    expect(rewriteRefWidth('{{table:100|view=9|limit=5}}', {
      kind: 'table', id: 100, occurrence: 0, width: 50,
    })).toBe('{{table:100|view=9|limit=5|width=50}}')
  })

  it('已有 width 时替换，其他参数顺序不变', () => {
    expect(rewriteRefWidth('{{table:100|view=9|width=50|limit=5}}', {
      kind: 'table', id: 100, occurrence: 0, width: 100,
    })).toBe('{{table:100|view=9|limit=5|width=100}}')
  })

  it('同一 ID 多次引用按出现序号只改目标段落', () => {
    const content = `前文\n\n{{chart:300}}\n\n中间\n\n{{chart:300}}\n\n后文`
    const next = rewriteRefWidth(content, { kind: 'chart', id: 300, occurrence: 1, width: 25 })
    expect(next).toBe(`前文\n\n{{chart:300}}\n\n中间\n\n{{chart:300|width=25}}\n\n后文`)
  })

  it('同文档不同 ID / 不同 kind 互不影响', () => {
    const content = '{{chart:300}}\n\n{{table:300}}\n\n{{chart:301}}'
    const next = rewriteRefWidth(content, { kind: 'table', id: 300, occurrence: 0, width: 50 })
    expect(next).toBe('{{chart:300}}\n\n{{table:300|width=50}}\n\n{{chart:301}}')
  })

  it('未命中出现序号时原样返回', () => {
    const content = '{{chart:300}}'
    expect(rewriteRefWidth(content, { kind: 'chart', id: 300, occurrence: 2, width: 50 })).toBe(content)
    expect(rewriteRefWidth(content, { kind: 'chart', id: 999, occurrence: 0, width: 50 })).toBe(content)
  })

  it('保留段内首尾空白', () => {
    expect(rewriteRefWidth('  {{chart:300}}  ', { kind: 'chart', id: 300, occurrence: 0, width: 50 }))
      .toBe('  {{chart:300|width=50}}  ')
  })

  it('非法宽度在写入时归一为 75', () => {
    expect(rewriteRefWidth('{{chart:300}}', { kind: 'chart', id: 300, occurrence: 0, width: 101 }))
      .toBe(`{{chart:300|width=${DEFAULT_REF_WIDTH}}}`)
  })
})

/** 正文引用切片测试（ADR 0045 / 0052）：数据表占位符 + 图表内嵌块混合. */

import { describe, expect, it } from 'vitest'
import { splitRefs } from './refs'
import { serializeChartBlock } from './chartBlock'

const chart = serializeChartBlock({ version: 1, templateKey: 'bar-line-dual-axis', title: '图', width: 75, config: {} })

describe('splitRefs', () => {
  it('空正文返回空数组', () => {
    expect(splitRefs('')).toEqual([])
  })

  it('无引用时整篇为 md 片段', () => {
    const text = '# 标题\n\n正文。\n'
    expect(splitRefs(text)).toEqual([{ type: 'md', text }])
  })

  it('图表块独占段落切为 chart 片段', () => {
    const segments = splitRefs(`# 标题\n\n${chart}\n\n正文。\n`)
    expect(segments.map(s => s.type)).toEqual(['md', 'chart', 'md'])
    const chartSeg = segments[1]
    expect(chartSeg.type === 'chart' && chartSeg.block.spec?.templateKey).toBe('bar-line-dual-axis')
  })

  it('数据表与图表可共存', () => {
    const segments = splitRefs(`{{table:100|limit=5}}\n\n${chart}\n\n正文`)
    expect(segments.map(s => s.type)).toEqual(['table', 'chart', 'md'])
  })

  it('chartsOnly 时数据表留在 md 文本（游客页只渲染图表）', () => {
    const segments = splitRefs(`{{table:100}}\n\n${chart}\n\n正文`, { chartsOnly: true })
    expect(segments.map(s => s.type)).toEqual(['md', 'chart', 'md'])
    expect(segments[0].type === 'md' && segments[0].text).toContain('{{table:100}}')
  })

  it('行内混排的图表围栏不解析', () => {
    const text = `前文 ${chart} 后文`
    expect(splitRefs(text)).toEqual([{ type: 'md', text }])
  })

  it('坏块仍切成 chart 片段供降级展示', () => {
    const segments = splitRefs('```chart\n{bad}\n```')
    expect(segments).toHaveLength(1)
    expect(segments[0].type).toBe('chart')
    expect(segments[0].type === 'chart' && segments[0].block.error).toBe('json_invalid')
  })
})

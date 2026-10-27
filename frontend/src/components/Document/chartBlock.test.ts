/** 正文内嵌图表块纯函数测试（ADR 0052）：解析 / 序列化 / 定位改写 / 上限 / 坏块. */

import { describe, expect, it } from 'vitest'
import {
  INLINE_CHART_VERSION,
  MAX_BLOCK_BYTES,
  chartBlockBytes,
  chartBlockErrorText,
  iterChartBlocks,
  parseChartBlock,
  rewriteChartBlock,
  rewriteChartBlockWidth,
  serializeChartBlock,
  type ChartBlockSpec,
} from './chartBlock'

const TEMPLATE = 'bar-line-dual-axis'

function spec(overrides: Partial<ChartBlockSpec> = {}): ChartBlockSpec {
  return { version: 1, templateKey: TEMPLATE, title: '营收趋势', width: 75, config: {}, ...overrides }
}

function source(overrides: Record<string, unknown> = {}, fence = '```'): string {
  const payload = { version: 1, template: TEMPLATE, title: '营收趋势', width: 60, config: {}, ...overrides }
  return `${fence}chart\n${JSON.stringify(payload)}\n${fence}`
}

describe('parseChartBlock', () => {
  it('解析合法块并归一默认值', () => {
    const block = parseChartBlock(source())
    expect(block?.error).toBeUndefined()
    expect(block?.spec).toMatchObject({
      version: INLINE_CHART_VERSION,
      templateKey: TEMPLATE,
      title: '营收趋势',
      width: 60,
      config: {},
    })
  })

  it('缺少 width / title 时回退默认', () => {
    const block = parseChartBlock(source({ width: undefined, title: undefined }))
    expect(block?.spec?.width).toBe(75)
    expect(block?.spec?.title).toBe('')
  })

  it('非法宽度回退 75', () => {
    expect(parseChartBlock(source({ width: 120 }))?.spec?.width).toBe(75)
    expect(parseChartBlock(source({ width: 'abc' }))?.spec?.width).toBe(75)
    expect(parseChartBlock(source({ width: 25 }))?.spec?.width).toBe(25)
  })

  it('支持 3 / 4 个反引号围栏', () => {
    expect(parseChartBlock(source({}, '````'))?.spec?.templateKey).toBe(TEMPLATE)
  })

  it('非图表块 / 行内混排 / 未闭合围栏不解析', () => {
    expect(parseChartBlock('普通段落')).toBeNull()
    expect(parseChartBlock('```json\n{}\n```')).toBeNull()
    expect(parseChartBlock(`前文 ${source()}`)).toBeNull()
    expect(parseChartBlock('```chart\n{"template":"x"}')).toBeNull()
  })

  it('序列化 → 解析往返一致', () => {
    const block = parseChartBlock(serializeChartBlock(spec({ width: 80, config: { data: { rows: [] } } })))
    expect(block?.spec?.width).toBe(80)
    expect(block?.spec?.config).toEqual({ data: { rows: [] } })
  })

  it('保留未知顶层字段（手改可修复）', () => {
    const block = parseChartBlock(source({ note: '手写字段' }))
    expect(block?.spec?.extra).toEqual({ note: '手写字段' })
    expect(serializeChartBlock(block!.spec!)).toContain('手写字段')
  })

  it('legacy_id 仅迁移期字段，随块保留', () => {
    const block = parseChartBlock(source({ legacy_id: 7 }))
    expect(block?.spec?.legacyId).toBe(7)
    expect(serializeChartBlock(block!.spec!)).toContain('"legacy_id": 7')
  })
})

describe('坏块错误码', () => {
  it.each([
    ['```chart\n{bad json}\n```', 'json_invalid'],
    ['```chart\n[]\n```', 'json_invalid'],
    [source({ version: 2 }), 'version_unsupported'],
    [source({ template: '' }), 'template_missing'],
    [source({ config: 'bad' }), 'config_invalid'],
  ])('%s → %s', (text, code) => {
    const block = parseChartBlock(text)
    expect(block?.spec).toBeNull()
    expect(block?.error).toBe(code)
    expect(chartBlockErrorText(block!.error!)).toContain('图表定义无效')
  })

  it('超过 32KB 的定义降级', () => {
    const block = parseChartBlock(source({ config: { x: 'a'.repeat(MAX_BLOCK_BYTES) } }))
    expect(block?.error).toBe('too_large')
  })
})

describe('定位改写', () => {
  it('按出现序号替换目标块，其余块与正文不变', () => {
    const first = serializeChartBlock(spec({ title: '图一' }))
    const second = serializeChartBlock(spec({ title: '图二' }))
    const content = `前言\n\n${first}\n\n中间\n\n${second}\n\n结尾`
    const next = rewriteChartBlock(content, 1, spec({ title: '图二改' }))
    expect(next).toContain('"title": "图一"')
    expect(next).toContain('"title": "图二改"')
    expect(next).not.toContain('"title": "图二"')
    expect(next.split('```chart').length - 1).toBe(2)
  })

  it('未命中出现序号时原样返回', () => {
    const content = `正文\n\n${serializeChartBlock(spec())}`
    expect(rewriteChartBlock(content, 3, spec({ title: 'x' }))).toBe(content)
    expect(rewriteChartBlock('', 0, spec())).toBe('')
  })

  it('按出现序号改写宽度（写入块字段）', () => {
    const content = `${serializeChartBlock(spec())}\n\n正文\n\n${serializeChartBlock(spec())}`
    const next = rewriteChartBlockWidth(content, 1, 40)
    expect(next.match(/"width": 75/g) ?? []).toHaveLength(1)
    expect(next).toContain('"width": 40')
    expect(rewriteChartBlockWidth(content, 5, 40)).toBe(content)
  })

  it('计数与体积辅助', () => {
    const content = `${serializeChartBlock(spec())}\n\n${serializeChartBlock(spec())}`
    expect(iterChartBlocks(content)).toHaveLength(2)
    expect(iterChartBlocks('正文')).toHaveLength(0)
    expect(chartBlockBytes(spec())).toBeGreaterThan(0)
    expect(chartBlockBytes(spec())).toBeLessThan(MAX_BLOCK_BYTES)
  })
})

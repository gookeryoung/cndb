/** 领域模板套用：字段映射对齐单测 */

import { describe, expect, it } from 'vitest'
import { materializeDomainTemplate } from './domainTemplate'
import type { DomainTemplate } from '@/api'

function template(overrides: Partial<DomainTemplate> = {}): DomainTemplate {
  return {
    id: 'tpl',
    provider: 'tencent_kline',
    name: '趋势',
    description: '',
    formulas: [
      { key: 'ma5', label: '5日均线', expr: 'round(ma([close], 5), 2)', partition_by: 'symbol', order_by: 'trade_date' },
    ],
    chart: { type: 'line', x: 'trade_date', y: 'close', series: 'symbol', title: '收盘价', aggregation: 'avg' },
    summary: {
      group_by: 'symbol',
      metrics: [
        { field: 'close', agg: 'avg', label: '平均收盘' },
        { field: 'symbol', agg: 'count', label: '交易日数' },
      ],
      sort_by: 'avg(close)',
      sort_order: 'desc',
      top_n: 20,
    },
    ...overrides,
  }
}

describe('materializeDomainTemplate', () => {
  it('无字段映射时原样保留模板配置', () => {
    const { config, skipped } = materializeDomainTemplate(template(), {})
    expect(skipped).toEqual([])
    expect(config.formulas[0]).toMatchObject({ expr: 'round(ma([close], 5), 2)', partition_by: 'symbol', order_by: 'trade_date' })
    expect(config.chart).toMatchObject({ x: 'trade_date', y: 'close', series: 'symbol' })
    expect(config.summary?.metrics.map(m => m.field)).toEqual(['close', 'symbol'])
    expect(config.summary?.sort_by).toBe('avg(close)')
    expect(config.limit).toBe(1000)
  })

  it('按 field_mapping 改名：公式、窗口字段、图表、汇总一起翻译', () => {
    const { config, skipped } = materializeDomainTemplate(template(), {
      close: { name: '收盘价', field_type: 'float' },
      trade_date: '交易日',
      symbol: { name: '代码' },
    })
    expect(skipped).toEqual([])
    expect(config.formulas[0]).toMatchObject({
      expr: 'round(ma([收盘价], 5), 2)',
      partition_by: '代码',
      order_by: '交易日',
    })
    expect(config.chart).toMatchObject({ x: '交易日', y: '收盘价', series: '代码' })
    expect(config.summary).toMatchObject({ group_by: '代码', sort_by: 'avg(收盘价)' })
    expect(config.summary?.metrics.map(m => m.field)).toEqual(['收盘价', '代码'])
  })

  it('字段被映射丢弃：剔除公式与图表，不退化成整份失败', () => {
    const { config, skipped } = materializeDomainTemplate(template(), { close: null })
    expect(config.formulas).toEqual([])
    expect(config.chart).toBeNull()
    expect(config.summary?.metrics.map(m => m.field)).toEqual(['symbol'])
    expect(config.summary?.sort_by).toBeNull()
    expect(skipped).toEqual(['公式「5日均线」', '图表「收盘价」', '汇总指标「平均收盘」'])
  })

  it('公式被剔除时，引用该 key 的图表与汇总一并剔除', () => {
    const tpl = template({
      formulas: [{ key: 'amp', label: '振幅', expr: 'round([high] - [low], 2)' }],
      chart: { type: 'bar', x: 'trade_date', y: 'amp', series: null, title: '振幅', aggregation: 'avg' },
      summary: {
        group_by: 'symbol',
        metrics: [{ field: 'amp', agg: 'avg', label: '平均振幅' }],
        sort_by: 'avg(amp)',
      },
    })
    const { config } = materializeDomainTemplate(tpl, { high: null })
    expect(config.formulas).toEqual([])
    expect(config.chart).toBeNull()
    expect(config.summary).toBeNull()
  })

  it('无公式模板（新闻类）只翻译图表与汇总字段', () => {
    const tpl = template({
      provider: 'rss_atom',
      formulas: [],
      chart: { type: 'bar', x: 'source', y: 'link', series: null, title: '来源', aggregation: 'count' },
      summary: { group_by: 'source', metrics: [{ field: 'link', agg: 'count', label: '条数' }], sort_by: 'count(link)' },
    })
    const { config } = materializeDomainTemplate(tpl, { source: '来源', link: '链接' })
    expect(config.chart).toMatchObject({ x: '来源', y: '链接' })
    expect(config.summary).toMatchObject({ group_by: '来源', sort_by: 'count(链接)' })
  })
})

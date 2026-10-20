/**
 * klineBoard 纯逻辑层测试 —— 行内 K 线解析 / 周期重采样 / 均线 / option 装配.
 *
 * 覆盖：字符串与数组形态、别名键、数值字符串、无效行剔除、升序去重（后写覆盖）/
 * 非法 JSON 与非数组错误 / 周月聚合口径（首开末收、最高最低、量额求和）/
 * MA 空值与样本不足 / 周月序列优先专用列、缺失时由日线同复权口径派生、未配置空态 /
 * 双 grid 与单 grid、dataZoom 初始窗口、红涨绿跌、tooltip 与成交量轴格式化。
 */

import { describe, expect, it } from 'vitest'
import type { RowResponse } from '@/api'
import {
  buildKlineOption,
  compactNumber,
  computeMA,
  formatNumber,
  formatPct,
  formatPrice,
  latestQuote,
  parseKlineSeries,
  parseKlineSeriesDetailed,
  parseMaPeriods,
  resampleKline,
  resolveSeries,
  type KlineConfig,
  type KlinePoint,
} from './klineBoard'

// ── 公共夹具 ──────────────────────────────────────────

function point(partial: Partial<KlinePoint> & { date: string }): KlinePoint {
  return {
    open: 0, close: 0, high: 0, low: 0,
    volume: null, amount: null, amplitude: null,
    pct_change: null, change: null, turnover: null,
    ...partial,
  }
}

/** 跨两个 ISO 周的日线（2026-01-05 起为 ISO 2026-W02） */
const DAILY: KlinePoint[] = [
  point({ date: '2026-01-05', open: 10, close: 11, high: 11.5, low: 9.8, volume: 100, amount: 1000, turnover: 1 }),
  point({ date: '2026-01-06', open: 11, close: 10.5, high: 11.2, low: 10.2, volume: 200, amount: 2000, turnover: 2 }),
  point({ date: '2026-01-12', open: 10.5, close: 12, high: 12.5, low: 10.4, volume: 300, amount: 3000, turnover: 3 }),
]

function row(values: Record<string, unknown>): RowResponse {
  return values as unknown as RowResponse
}

const CFG: KlineConfig = {
  symbol_field: '股票代码',
  name_field: '股票名称',
  price_field: '最新价',
  change_pct_field: '涨跌幅',
  day_qfq_field: '日线前复权',
  day_hfq_field: '日线后复权',
  day_none_field: '日线不复权',
  week_qfq_field: '周线前复权',
  month_qfq_field: '月线前复权',
}

// ── parseKlineSeries ──────────────────────────────────

describe('parseKlineSeries 序列解析', () => {
  it('JSON 字符串形态：升序排序、同一日期后写覆盖、无效行剔除', () => {
    const raw = JSON.stringify([
      { date: '2026-01-03', open: 3, close: 3.5, high: 4, low: 2.9 },
      { date: '2026-01-01', open: 1, close: 1.5, high: 2, low: 0.9 },
      { date: '2026-01-03', open: 30, close: 35, high: 40, low: 29, volume: 9 },
      { date: '2026-01-02', open: 'x', close: 2, high: 2, low: 1 },
      { open: 1, close: 1, high: 1, low: 1 },
    ])
    const points = parseKlineSeries(raw)
    expect(points.map((p) => p.date)).toEqual(['2026-01-01', '2026-01-03'])
    expect(points[1].open).toBe(30)
    expect(points[1].volume).toBe(9)
  })

  it('数组形态 + 别名键 + 数值字符串', () => {
    const points = parseKlineSeries([
      { 交易日: '2026-02-02', 开盘价: '10.5', 收盘价: '11', 最高价: '11.2', 最低价: '10.1', 成交量: '12345', 涨跌幅: '4.76' },
      { trade_date: '2026-02-03', o: 11, c: 12, h: 12.5, l: 10.9, vol: 200, amount: 2400 },
    ])
    expect(points).toHaveLength(2)
    expect(points[0]).toMatchObject({
      date: '2026-02-02', open: 10.5, close: 11, high: 11.2, low: 10.1,
      volume: 12345, pct_change: 4.76,
    })
    expect(points[1]).toMatchObject({ date: '2026-02-03', open: 11, close: 12, volume: 200, amount: 2400 })
  })

  it('紧凑元组形态 [date, open, close, high, low, volume?]', () => {
    const points = parseKlineSeries([['2026-03-02', 10, 11, 11.5, 9.5, 800]])
    expect(points).toEqual([
      point({ date: '2026-03-02', open: 10, close: 11, high: 11.5, low: 9.5, volume: 800 }),
    ])
  })

  it('YYYYMMDD 日期归一为 YYYY-MM-DD', () => {
    expect(parseKlineSeries([{ date: 20260105, open: 1, close: 1, high: 1, low: 1 }])[0].date).toBe('2026-01-05')
    expect(parseKlineSeries([{ date: '20260106', open: 1, close: 1, high: 1, low: 1 }])[0].date).toBe('2026-01-06')
  })

  it('空值与非法输入：空序列不报错，非法 JSON/非数组/全无效行返回 error', () => {
    expect(parseKlineSeriesDetailed(null)).toEqual({ points: [] })
    expect(parseKlineSeriesDetailed('')).toEqual({ points: [] })
    expect(parseKlineSeriesDetailed('null')).toEqual({ points: [] })
    expect(parseKlineSeriesDetailed([])).toEqual({ points: [] })

    expect(parseKlineSeriesDetailed('{bad json').error).toBe('K 线 JSON 解析失败')
    expect(parseKlineSeriesDetailed(JSON.stringify({ a: 1 })).error).toBe('K 线数据不是数组')
    expect(parseKlineSeriesDetailed([{ foo: 1 }]).error).toBe('K 线数据缺少有效日期或开高低收')
  })
})

// ── resampleKline ─────────────────────────────────────

describe('resampleKline 周期重采样', () => {
  it('周线：首开末收、最高最大、最低最小、量额求和、涨跌幅按周期首开重算', () => {
    const weekly = resampleKline(DAILY, 'week')
    expect(weekly).toHaveLength(2)

    expect(weekly[0]).toMatchObject({
      date: '2026-01-06',
      open: 10,
      close: 10.5,
      high: 11.5,
      low: 9.8,
      volume: 300,
      amount: 3000,
      turnover: 3,
      change: 0.5,
    })
    expect(weekly[0].pct_change).toBeCloseTo(5, 10)
    expect(weekly[0].amplitude).toBeCloseTo(17, 10)

    expect(weekly[1]).toMatchObject({ date: '2026-01-12', open: 10.5, close: 12, volume: 300 })
    expect(weekly[1].pct_change).toBeCloseTo((12 - 10.5) / 10.5 * 100, 10)
  })

  it('月线：按 YYYY-MM 分组', () => {
    const monthly = resampleKline(DAILY, 'month')
    expect(monthly.map((p) => p.date)).toEqual(['2026-01-12'])
    expect(monthly[0]).toMatchObject({ open: 10, close: 12, high: 12.5, low: 9.8, volume: 600, amount: 6000 })
  })

  it('空输入返回空数组；量额全空保持 null（不虚构 0）', () => {
    expect(resampleKline([], 'week')).toEqual([])
    const weekly = resampleKline([
      point({ date: '2026-01-05', open: 1, close: 1, high: 1, low: 1 }),
      point({ date: '2026-01-06', open: 1, close: 1, high: 1, low: 1 }),
    ], 'week')
    expect(weekly[0].volume).toBeNull()
    expect(weekly[0].amount).toBeNull()
  })
})

// ── computeMA / parseMaPeriods ────────────────────────

describe('computeMA 均线', () => {
  it('滑动窗口均值；样本不足为 null', () => {
    expect(computeMA([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4])
    expect(computeMA([1, 2], 5)).toEqual([null, null])
  })

  it('窗口内含空值返回 null，窗口滑出后恢复', () => {
    expect(computeMA([1, null, 3, 4, 5], 2)).toEqual([null, null, null, 3.5, 4.5])
  })

  it('非法周期返回全 null', () => {
    expect(computeMA([1, 2, 3], 0)).toEqual([null, null, null])
    expect(computeMA([1, 2, 3], -5)).toEqual([null, null, null])
  })
})

describe('parseMaPeriods 配置解析', () => {
  it('逗号分隔字符串 / 数组 / 去重 / 过滤非法值', () => {
    expect(parseMaPeriods('5,10,20,60')).toEqual([5, 10, 20, 60])
    expect(parseMaPeriods([5, 5, '10', -1, 0, 'abc', 999])).toEqual([5, 10])
    expect(parseMaPeriods(undefined)).toEqual([5, 10, 20, 60])
    expect(parseMaPeriods('')).toEqual([5, 10, 20, 60])
  })
})

// ── resolveSeries ─────────────────────────────────────

describe('resolveSeries 序列选择', () => {
  const baseRow = row({
    股票代码: 'sh600519',
    日线前复权: JSON.stringify(DAILY),
    日线后复权: null,
    日线不复权: null,
  })

  it('日线对应复权列直接命中', () => {
    const r = resolveSeries(baseRow, CFG, 'day', 'qfq')
    expect(r.source).toBe('column')
    expect(r.field).toBe('日线前复权')
    expect(r.points).toHaveLength(3)
  })

  it('周线专用列为空时由日线同复权口径派生', () => {
    const r = resolveSeries(baseRow, CFG, 'week', 'qfq')
    expect(r.source).toBe('derived')
    expect(r.field).toBe('日线前复权')
    expect(r.points).toHaveLength(2)
  })

  it('周线专用列存在时优先使用专用列', () => {
    const weeklyRows = row({
      ...baseRow,
      周线前复权: JSON.stringify([{ date: '2026-01-09', open: 10, close: 11, high: 12, low: 9, volume: 1 }]),
    })
    const r = resolveSeries(weeklyRows, CFG, 'week', 'qfq')
    expect(r.source).toBe('column')
    expect(r.field).toBe('周线前复权')
    expect(r.points).toHaveLength(1)
  })

  it('未配置对应复权口径的字段 → 空态并给出可读原因（不跨口径冒充）', () => {
    const cfgNoHfq: KlineConfig = { ...CFG, day_hfq_field: undefined, day_none_field: undefined }
    const r = resolveSeries(baseRow, cfgNoHfq, 'week', 'hfq')
    expect(r.points).toEqual([])
    expect(r.source).toBe('empty')
    expect(r.message).toBe('未配置周线后复权字段（视图设置）')

    const r2 = resolveSeries(baseRow, cfgNoHfq, 'day', 'none')
    expect(r2.message).toBe('未配置日线不复权字段（视图设置）')
  })

  it('日线同复权列为空时周线派生结果为空 → 暂无数据', () => {
    const r = resolveSeries(baseRow, CFG, 'week', 'hfq')
    expect(r.points).toEqual([])
    expect(r.message).toBe('周线后复权暂无数据')
  })

  it('字段已配置但无数据 → 暂无数据；JSON 解析失败保留 error', () => {
    expect(resolveSeries(row({}), CFG, 'day', 'qfq').message).toBe('日线前复权暂无数据')

    const broken = resolveSeries(row({ 日线前复权: '{bad' }), CFG, 'day', 'qfq')
    expect(broken.points).toEqual([])
    expect(broken.message).toBe('日线前复权暂无数据')
    expect(broken.error).toContain('日线前复权')
    expect(broken.error).toContain('解析失败')
  })
})

// ── 行情取值与格式化 ──────────────────────────────────

describe('latestQuote 与格式化', () => {
  it('取升序序列末位；空序列返回 null', () => {
    expect(latestQuote(DAILY)?.date).toBe('2026-01-12')
    expect(latestQuote([])).toBeNull()
  })

  it('formatPrice / formatNumber / compactNumber / formatPct', () => {
    expect(formatPrice(null)).toBe('—')
    expect(formatPrice(12)).toBe('12')
    expect(formatPrice(12.34567)).toBe('12.35')
    expect(formatPrice(1700.5)).toBe('1700.50')
    expect(formatNumber(1.234567)).toBe('1.23457')
    expect(compactNumber(null)).toBe('—')
    expect(compactNumber(9999)).toBe('9999')
    expect(compactNumber(15000)).toBe('1.5万')
    expect(compactNumber(2.5e8)).toBe('2.5亿')
    expect(formatPct(5.2)).toBe('+5.20%')
    expect(formatPct(-3.1)).toBe('-3.10%')
    expect(formatPct(null)).toBe('—')
  })
})

// ── buildKlineOption ──────────────────────────────────

const OPTION_POINTS: KlinePoint[] = ['10', '11', '12', '13', '14', '15'].map((c, i) => point({
  date: `2026-01-0${i + 1}`,
  open: Number(c) - 0.5,
  close: Number(c),
  high: Number(c) + 0.5,
  low: Number(c) - 1,
  volume: (i + 1) * 10000,
  amount: (i + 1) * 1e8,
  pct_change: i === 5 ? 4.76 : -1.2,
  change: i === 5 ? 0.68 : -0.1,
}))

/** 以宽松类型读取 option 子结构（纯装配测试，无需 ECharts 类型体操） */
function opt(o: Record<string, unknown>, key: string): any {
  return o[key]
}

describe('buildKlineOption 装配', () => {
  it('默认双 grid + 双 xAxis + MA 系列 + 初始窗口百分比', () => {
    const o = buildKlineOption(OPTION_POINTS, { windowSize: 5, maPeriods: [5] })
    expect(opt(o, 'grid')).toHaveLength(2)
    expect(opt(o, 'xAxis')).toHaveLength(2)
    expect(opt(o, 'yAxis')).toHaveLength(2)

    const series = opt(o, 'series') as Array<Record<string, unknown>>
    expect(series.map((s) => s.name)).toEqual(['K线', 'MA5', '成交量'])
    // MA5 末值 = 最近 5 根收盘均值
    expect((series[1].data as Array<number | null>)[5]).toBeCloseTo((11 + 12 + 13 + 14 + 15) / 5, 10)

    // 6 根 K 线、窗口 5 → start = 1/6
    const zoom = opt(o, 'dataZoom') as Array<Record<string, unknown>>
    expect(zoom[0].start).toBeCloseTo((1 / 6) * 100, 6)
    expect(zoom[0].xAxisIndex).toEqual([0, 1])

    // 红涨绿跌
    expect(series[0].itemStyle).toMatchObject({ color: '#ef5350', color0: '#26a69a' })
  })

  it('showVolume=false 退化为单 grid，且不生成成交量系列', () => {
    const o = buildKlineOption(OPTION_POINTS, { showVolume: false, showMa: false })
    expect(opt(o, 'grid')).toHaveLength(1)
    expect(opt(o, 'xAxis')).toHaveLength(1)
    expect(opt(o, 'yAxis')).toHaveLength(1)
    expect(opt(o, 'legend')).toBeUndefined()
    const series = opt(o, 'series') as Array<Record<string, unknown>>
    expect(series.map((s) => s.name)).toEqual(['K线'])
    expect((opt(o, 'dataZoom') as Array<Record<string, unknown>>)[0].xAxisIndex).toEqual([0])
  })

  it('candlestick 数据为 ECharts 口径 [open, close, low, high]；成交量轴刻度缩写', () => {
    const o = buildKlineOption(OPTION_POINTS, { maPeriods: [5] })
    const series = opt(o, 'series') as Array<Record<string, unknown>>
    expect((series[0].data as number[][])[5]).toEqual([14.5, 15, 14, 15.5])

    const yAxis = opt(o, 'yAxis') as Array<Record<string, any>>
    expect(yAxis[1].axisLabel.formatter(15000)).toBe('1.5万')
  })

  it('tooltip 含日期/OHLC/涨跌幅/量额/均线值', () => {
    const o = buildKlineOption(OPTION_POINTS, { maPeriods: [5] })
    const formatter = opt(o, 'tooltip').formatter as (p: unknown) => string
    const html = formatter([{ dataIndex: 5 }])

    expect(html).toContain('2026-01-06')
    expect(html).toContain('开盘 14.50')
    expect(html).toContain('收盘')
    expect(html).toContain('最高 15.50')
    expect(html).toContain('涨跌幅')
    expect(html).toContain('+4.76%')
    expect(html).toContain('成交量 6万')
    expect(html).toContain('MA5')
    expect(html).toContain('13')
    // 越界索引返回空串（不抛异常）
    expect(formatter([{ dataIndex: 999 }])).toBe('')
    expect(formatter([{ dataIndex: -1 }])).toBe('')
  })

  it('空序列也能装配（不抛异常，series 仍为合法结构）', () => {
    const o = buildKlineOption([], {})
    expect(opt(o, 'xAxis')).toHaveLength(2)
    expect((opt(o, 'series') as unknown[]).length).toBe(6) // K线 + 4 条默认均线 + 成交量
  })
})

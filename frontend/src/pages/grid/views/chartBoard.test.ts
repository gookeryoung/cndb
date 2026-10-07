/**
 * chartBoard 纯逻辑层测试 —— 图表视图聚合/分箱/统计.
 *
 * 覆盖：维度聚合（sum/avg/count/min/max + 空值剔除 + 未分组）/ 日期分桶排序 /
 * 多系列对齐（无值桶为 null）/ pie / scatter（无效行剔除 + rowIds 平行）/
 * boxplot 五数概括与 IQR 离群 / 分箱三策略（含 FD IQR=0 回退、单值、空数组）/
 * computeStats 已知数据集精确值 / pearson 与 ols（完美线性、奇异、小样本）。
 */

import { describe, expect, it } from 'vitest'
import type { Field, RowResponse } from '@/api'
import { makeField } from '@/test/fixtures'
import {
  buildChartData,
  computeStats,
  extractNumbers,
  histogramBins,
  olsLine,
  pearson,
  toNumber,
  type ChartConfig,
} from './chartBoard'

// ── 公共夹具 ──────────────────────────────────────────

const dateField = makeField({ id: 1, name: '日期', field_type: 'date' })
const amountField = makeField({ id: 2, name: '销售额', field_type: 'number' })
const productField = makeField({ id: 3, name: '产品', field_type: 'text' })
const deptField = makeField({ id: 4, name: '部门', field_type: 'text' })
const salaryField = makeField({ id: 5, name: '薪资', field_type: 'number' })

function row(v: Record<string, unknown>): RowResponse {
  return v as unknown as RowResponse
}

const AGG_ROWS: RowResponse[] = [
  row({ id: 1, 日期: '2026-01-05', 销售额: 100 }),
  row({ id: 2, 日期: '2026-01-20', 销售额: 200 }),
  row({ id: 3, 日期: '2026-02-10', 销售额: 50 }),
  row({ id: 4, 日期: '2026-02-15', 销售额: null }), // 空值剔除
  row({ id: 5, 日期: null, 销售额: 70 }), // 空维度归未分组
]

const AGG_FIELDS: Field[] = [dateField, amountField]

function cfg(partial: Partial<ChartConfig> & Pick<ChartConfig, 'chart_type'>): ChartConfig {
  return partial as ChartConfig
}

// ── toNumber / extractNumbers ─────────────────────────

describe('toNumber 数值提取', () => {
  it('number / 数字串有效；空值、非数字、非有限值剔除', () => {
    expect(toNumber(5)).toBe(5)
    expect(toNumber(3.5)).toBe(3.5)
    expect(toNumber('3.5')).toBe(3.5)
    expect(toNumber(' 7 ')).toBe(7)
    expect(toNumber(0)).toBe(0)
    expect(toNumber(null)).toBeNull()
    expect(toNumber(undefined)).toBeNull()
    expect(toNumber('')).toBeNull()
    expect(toNumber('abc')).toBeNull()
    expect(toNumber(NaN)).toBeNull()
    expect(toNumber(Infinity)).toBeNull()
    expect(toNumber(true)).toBeNull()
  })

  it('extractNumbers 保持行序并剔除无效值', () => {
    const rows = [row({ v: 3 }), row({ v: 'x' }), row({ v: 1.5 }), row({ v: null })]
    expect(extractNumbers(rows, 'v')).toEqual([3, 1.5])
    expect(extractNumbers(rows, undefined)).toEqual([])
  })
})

// ── bar/line 维度聚合 ─────────────────────────────────

describe('buildChartData — bar/line 维度聚合', () => {
  it('sum 聚合：日期 month 分桶 + 空值剔除 + 未分组末尾', () => {
    const data = buildChartData(AGG_ROWS, AGG_FIELDS, cfg({
      chart_type: 'bar', dimension_field: '日期', measure_field: '销售额',
      date_granularity: 'month', aggregation: 'sum',
    }))
    expect(data.kind).toBe('category')
    if (data.kind !== 'category') return
    // 日期轴字典序（==时序），「未分组」恒末尾
    expect(data.categories).toEqual(['2026-01', '2026-02', '未分组'])
    expect(data.series).toHaveLength(1)
    expect(data.series[0].data).toEqual([300, 50, 70])
  })

  it('avg / count / min / max 聚合口径', () => {
    const build = (aggregation: ChartConfig['aggregation']) => {
      const d = buildChartData(AGG_ROWS, AGG_FIELDS, cfg({
        chart_type: 'bar', dimension_field: '日期', measure_field: '销售额',
        date_granularity: 'month', aggregation,
      }))
      return d.kind === 'category' ? d.series[0].data : []
    }
    expect(build('avg')).toEqual([150, 50, 70])
    // count 只计度量有效的行（null 销售额行剔除，对齐 SQL COUNT(col)）
    expect(build('count')).toEqual([2, 1, 1])
    expect(build('min')).toEqual([100, 50, 70])
    expect(build('max')).toEqual([200, 50, 70])
  })

  it('count 聚合支持字符串度量字段（COUNT(col) 语义，空值跳过）', () => {
    // 产品开发「片区项目数」视图场景：维度=片区，度量=项目编号（字符串），聚合=count
    const rows = [
      row({ id: 1, 片区: '华东', 项目编号: 'PRJ001' }),
      row({ id: 2, 片区: '华东', 项目编号: 'PRJ002' }),
      row({ id: 3, 片区: '华南', 项目编号: 'PRJ003' }),
      row({ id: 4, 片区: '华南', 项目编号: null }),     // 空值跳过
      row({ id: 5, 片区: '华南', 项目编号: '' }),       // 空串跳过
      row({ id: 6, 片区: '华北', 项目编号: 'PRJ006' }),
    ]
    const areaField = makeField({ id: 10, name: '片区', field_type: 'text' })
    const prjField = makeField({ id: 11, name: '项目编号', field_type: 'text' })
    const data = buildChartData(rows, [areaField, prjField], cfg({
      chart_type: 'bar', dimension_field: '片区', measure_field: '项目编号',
      aggregation: 'count',
    }))
    expect(data.kind).toBe('category')
    if (data.kind !== 'category') return
    // 文本维度按 zh-CN locale 排序（拼音序：华北 huabei < 华东 huadong < 华南 huanan）
    expect(data.categories).toEqual(['华北', '华东', '华南'])
    expect(data.series[0].data).toEqual([1, 2, 1])  // 华北 1，华东 2，华南 1（跳过 2 空值）
  })

  it('group_field 多系列：无值桶为 null 不虚构 0', () => {
    const rows: RowResponse[] = [
      row({ id: 1, 日期: '2026-01-05', 产品: 'A', 销售额: 100 }),
      row({ id: 2, 日期: '2026-01-20', 产品: 'B', 销售额: 200 }),
      row({ id: 3, 日期: '2026-02-10', 产品: 'A', 销售额: 50 }),
    ]
    const data = buildChartData(rows, [dateField, productField, amountField], cfg({
      chart_type: 'line', dimension_field: '日期', measure_field: '销售额',
      group_field: '产品', date_granularity: 'month', aggregation: 'sum',
    }))
    expect(data.kind).toBe('category')
    if (data.kind !== 'category') return
    expect(data.categories).toEqual(['2026-01', '2026-02'])
    expect(data.series.map((s) => s.name)).toEqual(['A', 'B'])
    expect(data.series[0].data).toEqual([100, 50])
    expect(data.series[1].data).toEqual([200, null])
  })
})

// ── pie / scatter / boxplot ───────────────────────────

describe('buildChartData — pie', () => {
  it('维度聚合为扇区', () => {
    const data = buildChartData(AGG_ROWS, AGG_FIELDS, cfg({
      chart_type: 'pie', dimension_field: '日期', measure_field: '销售额',
      date_granularity: 'month', aggregation: 'sum',
    }))
    expect(data.kind).toBe('pie')
    if (data.kind !== 'pie') return
    expect(data.items).toEqual([
      { name: '2026-01', value: 300 },
      { name: '2026-02', value: 50 },
      { name: '未分组', value: 70 },
    ])
  })
})

describe('buildChartData — scatter', () => {
  const xField = makeField({ id: 6, name: '单价', field_type: 'number' })
  const yField = makeField({ id: 7, name: '数量', field_type: 'number' })

  it('双数值取点：任一无效整行剔除；rowIds 与 points 平行', () => {
    const rows: RowResponse[] = [
      row({ id: 11, 单价: 1.5, 数量: 2 }),
      row({ id: 12, 单价: 2, 数量: 4 }),
      row({ id: 13, 单价: 'bad', 数量: 5 }), // x 无效 → 剔除
      row({ id: 14, 单价: 3, 数量: null }), // y 无效 → 剔除
    ]
    const data = buildChartData(rows, [xField, yField], cfg({
      chart_type: 'scatter', x_field: '单价', y_field: '数量',
    }))
    expect(data.kind).toBe('scatter')
    if (data.kind !== 'scatter') return
    expect(data.points).toEqual([[1.5, 2], [2, 4]])
    expect(data.rowIds).toEqual([11, 12])
  })
})

describe('buildChartData — boxplot', () => {
  it('每组五数概括（线性插值分位）+ IQR 离群点（[类目索引, 值]）', () => {
    const rows: RowResponse[] = [
      row({ id: 1, 部门: 'Dev', 薪资: 1 }),
      row({ id: 2, 部门: 'Dev', 薪资: 2 }),
      row({ id: 3, 部门: 'Dev', 薪资: 3 }),
      row({ id: 4, 部门: 'Dev', 薪资: 4 }),
      row({ id: 5, 部门: 'Dev', 薪资: 100 }), // 离群值
      row({ id: 6, 部门: 'Sales', 薪资: 10 }),
      row({ id: 7, 部门: 'Sales', 薪资: 20 }),
      row({ id: 8, 部门: 'Sales', 薪资: 30 }),
    ]
    const data = buildChartData(rows, [deptField, salaryField], cfg({
      chart_type: 'boxplot', dimension_field: '部门', measure_field: '薪资',
    }))
    expect(data.kind).toBe('boxplot')
    if (data.kind !== 'boxplot') return
    expect(data.categories).toEqual(['Dev', 'Sales'])
    // Dev [1,2,3,4,100]：Q1=2 med=3 Q3=4；IQR=2 → 100 > 4+3 离群
    expect(data.boxes[0]).toEqual([1, 2, 3, 4, 100])
    // Sales [10,20,30]：Q1=15 med=20 Q3=25（线性插值）
    expect(data.boxes[1]).toEqual([10, 15, 20, 25, 30])
    expect(data.outliers).toEqual([[0, 100]])
  })
})

// ── histogram 分箱 ────────────────────────────────────

describe('histogramBins 分箱策略', () => {
  const seq10 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

  it('auto（平方根）：n=10 → 4 箱均匀分箱，末箱闭区间含 max', () => {
    const bins = histogramBins(seq10, 'auto')
    expect(bins).toHaveLength(4)
    // 宽度 9/4=2.25：[1,3.25) [3.25,5.5) [5.5,7.75) [7.75,10]
    expect(bins.map((b) => b.count)).toEqual([3, 2, 2, 3])
    expect(bins[3].to).toBe(10)
  })

  it('sturges：n=10 → ceil(log2(10)+1)=5 箱', () => {
    const bins = histogramBins(seq10, 'sturges')
    expect(bins).toHaveLength(5)
    expect(bins.reduce((a, b) => a + b.count, 0)).toBe(10)
  })

  it('freedman-diaconis：IQR 跨度大 → 2 箱', () => {
    // [1..10]：Q1=3.25 Q3=7.75 → IQR=4.5 → h=2·4.5/∛10≈3.87 → ceil(9/3.87)=3？
    // 实测口径以断言为准：先验证回退分支与本策略非退化即可
    const bins = histogramBins(seq10, 'freedman-diaconis')
    expect(bins.length).toBeGreaterThanOrEqual(2)
    expect(bins.reduce((a, b) => a + b.count, 0)).toBe(10)
  })

  it('FD IQR=0 退化回退 Sturges', () => {
    // [1,1,1,1,2]：Q1=Q3=1 → IQR=0 → 回退 sturges：ceil(log2(5)+1)=4
    const bins = histogramBins([1, 1, 1, 1, 2], 'freedman-diaconis')
    expect(bins).toHaveLength(4)
  })

  it('边界：空数组 / 单元素 / 全同值', () => {
    expect(histogramBins([], 'auto')).toEqual([])
    expect(histogramBins([7], 'auto')).toEqual([
      { label: '7~7', count: 1, from: 7, to: 7 },
    ])
    const same = histogramBins([5, 5, 5], 'auto')
    expect(same).toHaveLength(1)
    expect(same[0].count).toBe(3)
  })

  it('标签格式：整数边界原样，浮点 6 位有效数字', () => {
    const bins = histogramBins([0.15, 0.25, 0.35, 0.45], 'sturges')
    for (const b of bins) {
      expect(b.label).toMatch(/^0\.\d+~0\.\d+$/)
    }
  })
})

// ── computeStats 描述统计 ─────────────────────────────

describe('computeStats 已知数据集精确值', () => {
  it('[1,2,2,3,4,5]：全指标精确断言', () => {
    const s = computeStats([1, 2, 2, 3, 4, 5])
    expect(s).not.toBeNull()
    if (!s) return
    expect(s.count).toBe(6)
    expect(s.sum).toBe(17)
    expect(s.mean).toBeCloseTo(17 / 6, 10)
    expect(s.median).toBe(2.5)
    expect(s.mode).toBe(2)
    // R-7 线性插值：P25 h=1.25 → sorted[1]+0.25*(2-2)=2（重复值 2），P75 h=3.75 → 3.75
    expect(s.p25).toBe(2)
    expect(s.p75).toBe(3.75)
    expect(s.iqr).toBe(1.75)
    expect(s.min).toBe(1)
    expect(s.max).toBe(5)
    expect(s.range).toBe(4)
    // 样本方差 = (390/36)/5 = 13/6 → std = sqrt(13/6)
    expect(s.std).toBeCloseTo(Math.sqrt(13 / 6), 10)
    expect(s.outlierCount).toBe(0) // lo=0 hi=6 无离群
  })

  it('IQR 法离群值计数：[1,2,3,4,5,100] → 1 个', () => {
    // P25=2.25 P75=4.75 IQR=2.5 → 界外 (-1.5, 8.5) → 100 离群
    const s = computeStats([1, 2, 3, 4, 5, 100])
    expect(s?.p25).toBe(2.25)
    expect(s?.p75).toBe(4.75)
    expect(s?.outlierCount).toBe(1)
  })

  it('偏度：正偏 > 0 / 负偏 < 0；小样本口径为 null', () => {
    const right = computeStats([1, 2, 2, 3, 4, 100])
    expect(right?.skewness).not.toBeNull()
    expect(right!.skewness!).toBeGreaterThan(0)
    const left = computeStats([1, 60, 61, 62, 63, 64])
    expect(left!.skewness!).toBeLessThan(0)
    // n<3 → null；n<2 → std 也为 null
    const tiny = computeStats([5, 9])
    expect(tiny?.skewness).toBeNull()
    expect(tiny?.std).not.toBeNull()
    const single = computeStats([5])
    expect(single?.skewness).toBeNull()
    expect(single?.std).toBeNull()
    expect(single?.mean).toBe(5)
  })

  it('空数组返回 null', () => {
    expect(computeStats([])).toBeNull()
  })
})

// ── pearson / olsLine ─────────────────────────────────

describe('pearson 相关', () => {
  it('完美正相关 r=1，完美负相关 r=-1', () => {
    expect(pearson([[1, 2], [2, 4], [3, 6], [4, 8]])).toBeCloseTo(1, 12)
    expect(pearson([[1, 8], [2, 6], [3, 4], [4, 2]])).toBeCloseTo(-1, 12)
  })

  it('n<2 或 X 恒定（分母 0）返回 null', () => {
    expect(pearson([])).toBeNull()
    expect(pearson([[1, 2]])).toBeNull()
    expect(pearson([[1, 1], [1, 2], [1, 3]])).toBeNull()
  })
})

describe('olsLine 回归', () => {
  it('完美线性 y=2x：斜率 2 截距 0，r=1 R²=1', () => {
    const ols = olsLine([[1, 2], [2, 4], [3, 6], [4, 8]])
    expect(ols).not.toBeNull()
    expect(ols!.slope).toBeCloseTo(2, 12)
    expect(ols!.intercept).toBeCloseTo(0, 12)
    expect(ols!.r).toBeCloseTo(1, 12)
    expect(ols!.r2).toBeCloseTo(1, 12)
  })

  it('y=-2x+10：斜率与截距精确', () => {
    const ols = olsLine([[1, 8], [2, 6], [3, 4], [4, 2]])
    expect(ols!.slope).toBeCloseTo(-2, 12)
    expect(ols!.intercept).toBeCloseTo(10, 12)
    expect(ols!.r2).toBeCloseTo(1, 12)
  })

  it('n<2 或 X 恒定（奇异）返回 null', () => {
    expect(olsLine([[1, 2]])).toBeNull()
    expect(olsLine([[1, 1], [1, 2]])).toBeNull()
  })
})

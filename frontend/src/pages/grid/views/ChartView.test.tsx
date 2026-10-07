/**
 * ChartView 组件测试 —— 图表视图.
 *
 * 覆盖：未配置必填字段空态 / 空数据空态 / bar 聚合 option 结构（类目序 + 未分组末尾 + notMerge）/
 * group_field 多系列与 legend / scatter 趋势线与 Pearson 摘要 / 统计面板数值与截断口径 /
 * show_stats_panel 关闭 / 主题切换联动重建 option。
 *
 * echarts/core 及子模块 mock：init 返回 fake chart（捕获 setOption/on/dispose），断言 option 纯结构。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import ChartView from './ChartView'
import { useTheme } from '@/theme/ThemeProvider'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

// ── echarts mock ────────────────────────────────────────
const echartsMock = vi.hoisted(() => {
  const setOption = vi.fn()
  const on = vi.fn()
  const resize = vi.fn()
  const dispose = vi.fn()
  const init = vi.fn(() => ({ setOption, on, resize, dispose }))
  return { init, setOption, on, resize, dispose }
})

vi.mock('echarts/core', () => ({ use: vi.fn(), init: echartsMock.init }))
vi.mock('echarts/charts', () => ({
  BarChart: {}, LineChart: {}, PieChart: {}, ScatterChart: {}, BoxplotChart: {},
}))
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, LegendComponent: {} }))
vi.mock('echarts/renderers', () => ({ SVGRenderer: {} }))

// ── 测试数据 ────────────────────────────────────────────

const FIELDS: Field[] = [
  makeField({ id: 1, name: '月份', field_type: 'date' }),
  makeField({ id: 2, name: '销售额', field_type: 'number' }),
  makeField({ id: 3, name: '团队', field_type: 'select', config: { options: ['研发组', '设计组'] } }),
  makeField({ id: 4, name: '工时', field_type: 'number' }),
]

const ROWS: RowResponse[] = [
  { id: 1, 月份: '2026-07-05', 销售额: 100, 团队: '研发组', 工时: 1 },
  { id: 2, 月份: '2026-08-10', 销售额: 50, 团队: '设计组', 工时: 2 },
  { id: 3, 月份: '2026-07-20', 销售额: 30, 团队: '研发组', 工时: 3 },
  { id: 4, 月份: null, 销售额: 90, 团队: '设计组', 工时: 4 },
  { id: 5, 月份: '2026-08-01', 销售额: null, 团队: '研发组', 工时: 5 },
] as unknown as RowResponse[]

function makeView(view_options: Record<string, unknown>): View {
  return { id: 1, name: '图表', view_type: 'chart', is_default: false, view_options } as unknown as View
}

function renderChart(props?: {
  rows?: RowResponse[]
  view?: View
  total?: number
  onRowClick?: (r: RowResponse) => void
}) {
  return renderProviders(
    <ChartView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={props?.view ?? makeView({
        chart_type: 'bar',
        dimension_field: '月份',
        measure_field: '销售额',
        aggregation: 'sum',
        date_granularity: 'month',
      })}
      total={props?.total}
      onRowClick={props?.onRowClick}
    />,
  )
}

beforeEach(() => {
  echartsMock.init.mockClear()
  echartsMock.setOption.mockClear()
  echartsMock.on.mockClear()
  echartsMock.dispose.mockClear()
})

describe('ChartView 图表视图', () => {
  it('未配置必填字段显示引导空态（不 init 图表）', () => {
    renderChart({ view: makeView({ chart_type: 'bar' }) })

    expect(screen.getByTestId('chart-empty-config')).toBeInTheDocument()
    expect(screen.getByText(/图表视图需配置维度字段与度量字段/)).toBeInTheDocument()
    expect(echartsMock.init).not.toHaveBeenCalled()
  })

  it('scatter 缺 X/Y 字段时空态提示相应字段', () => {
    renderChart({ view: makeView({ chart_type: 'scatter', y_field: '销售额' }) })

    expect(screen.getByTestId('chart-empty-config')).toBeInTheDocument()
    expect(screen.getByText(/X 数值字段/)).toBeInTheDocument()
  })

  it('空数据显示引导空态', () => {
    renderChart({ rows: [] })

    expect(screen.getByTestId('chart-empty-rows')).toBeInTheDocument()
    expect(screen.getByText(/这张表还没有数据/)).toBeInTheDocument()
  })

  it('bar：init SVG 容器并 setOption(notMerge)，类目按日期字典序、未分组末尾、sum 聚合', () => {
    renderChart({ total: 5 })

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.setOption).toHaveBeenCalledTimes(1)
    // notMerge 覆盖式更新（图表类型切换不残留旧系列）
    expect(echartsMock.setOption.mock.calls[0][1]).toBe(true)

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    expect(option.series).toHaveLength(1)
    expect(option.series[0].type).toBe('bar')
    expect(option.xAxis.type).toBe('category')
    expect(option.xAxis.data).toEqual(['2026-07', '2026-08', '未分组'])
    // 空度量行剔除：2026-08 只累计 50；维度空行归未分组 90
    expect(option.series[0].data).toEqual([130, 50, 90])
    expect(option.yAxis.type).toBe('value')
  })

  it('group_field 多系列：每系列一类目桶数据、无值桶为 null、legend 出现', () => {
    renderChart({
      view: makeView({
        chart_type: 'bar',
        dimension_field: '月份',
        measure_field: '销售额',
        aggregation: 'sum',
        date_granularity: 'month',
        group_field: '团队',
      }),
    })

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    expect(option.series).toHaveLength(2)
    // 分组系列名按 zh-CN 拼音序：she(设计) < yan(研发)
    expect(option.series.map((s: any) => s.name)).toEqual(['设计组', '研发组'])
    // 设计组：2026-07 无、2026-08=50、未分组=90
    expect(option.series[0].data).toEqual([null, 50, 90])
    // 研发组：2026-07 两行 100+30=130、2026-08 无有效值（null 不虚构 0）、未分组无行
    expect(option.series[1].data).toEqual([130, null, null])
    expect(option.legend).toBeDefined()
  })

  it('line 类型：series type 为 line', () => {
    renderChart({
      view: makeView({
        chart_type: 'line',
        dimension_field: '月份',
        measure_field: '销售额',
        aggregation: 'sum',
        date_granularity: 'month',
      }),
    })

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    expect(option.series[0].type).toBe('line')
  })

  it('scatter：双数值取点 + show_trend_line 追加 OLS 趋势线系列（两端点）', () => {
    renderChart({
      view: makeView({
        chart_type: 'scatter',
        x_field: '工时',
        y_field: '销售额',
        show_trend_line: true,
      }),
    })

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    // 散点（剔除销售额空值行，4 点）+ 趋势线
    expect(option.series).toHaveLength(2)
    expect(option.series[0].type).toBe('scatter')
    expect(option.series[0].data).toEqual([[1, 100], [2, 50], [3, 30], [4, 90]])
    const trend = option.series[1]
    expect(trend.type).toBe('line')
    expect(trend.silent).toBe(true)
    // OLS 两端点：x∈[1,4]（完美线性之外的噪声由最小二乘拟合，端点 x 取数据极值）
    expect(trend.data[0][0]).toBe(1)
    expect(trend.data[1][0]).toBe(4)
  })

  it('统计面板：均值/计数等数值 + 「样本量 N / 总行数 M」截断口径', () => {
    renderChart({ total: 5 })

    // 销售额有效值 [100,50,30,90]：count=4、sum=270、mean=67.5、min=30、max=100
    expect(screen.getByTestId('chart-stats-panel')).toBeInTheDocument()
    expect(screen.getByText('67.5')).toBeInTheDocument()
    expect(screen.getByTestId('chart-stats-scope')).toHaveTextContent('样本量 4 / 总行数 5')
  })

  it('散点统计面板附加 Pearson r / R² / 回归系数', () => {
    renderChart({
      view: makeView({
        chart_type: 'scatter',
        x_field: '工时',
        y_field: '工时', // 完美线性 y=x：r=1、R²=1、斜率 1、截距 0
      }),
    })

    expect(screen.getByText('Pearson r')).toBeInTheDocument()
    expect(screen.getByText('R²')).toBeInTheDocument()
    expect(screen.getByText('回归斜率')).toBeInTheDocument()
    expect(screen.getByText('回归截距')).toBeInTheDocument()
  })

  it('show_stats_panel=false 不渲染统计面板', () => {
    renderChart({
      view: makeView({
        chart_type: 'bar',
        dimension_field: '月份',
        measure_field: '销售额',
        aggregation: 'sum',
        date_granularity: 'month',
        show_stats_panel: false,
      }),
    })

    expect(screen.queryByTestId('chart-stats-panel')).not.toBeInTheDocument()
  })

  it('主题切换联动：setMode 触发 option 重建（getComputedStyle 重读 CSS 变量）', () => {
    function Harness() {
      const { setMode } = useTheme()
      return (
        <>
          <button type="button" onClick={() => setMode('github-dark')}>切主题</button>
          <ChartView
            rows={ROWS}
            fields={FIELDS}
            view={makeView({
              chart_type: 'bar',
              dimension_field: '月份',
              measure_field: '销售额',
              aggregation: 'sum',
              date_granularity: 'month',
            })}
          />
        </>
      )
    }
    renderProviders(<Harness />)

    expect(echartsMock.setOption).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByText('切主题'))
    // 主题 state 变化 → 重渲染 → option memo 失效 → setOption 重建
    expect(echartsMock.setOption).toHaveBeenCalledTimes(2)
    // 图表实例不重建（init 仍 1 次），仅覆盖 option
    expect(echartsMock.init).toHaveBeenCalledTimes(1)
  })

  it('pie：series[0].type=pie，data=[{name,value,itemStyle.color}]', () => {
    renderChart({
      view: makeView({
        chart_type: 'pie',
        dimension_field: '团队',
        measure_field: '销售额',
        aggregation: 'sum',
      }),
    })

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    expect(option.series).toHaveLength(1)
    expect(option.series[0].type).toBe('pie')
    // ROWS 里团队无空值，两个分组按拼音序：设计组 she < 研发组 yan
    // 设计组：id=2(50)+id=4(90)=140；研发组：id=1(100)+id=3(30)=130；id=5 销售额为 null 剔除
    const names = option.series[0].data.map((d: any) => d.name)
    expect(names).toEqual(['设计组', '研发组'])
    const values = option.series[0].data.map((d: any) => d.value)
    expect(values).toEqual([140, 130])
    // 每个扇区都有 itemStyle.color（按系列色循环）
    for (const d of option.series[0].data) {
      expect(d.itemStyle?.color).toBeDefined()
    }
  })

  it('histogram：series[0].type=bar、barCategoryGap=0、bins labels 做 xAxis', () => {
    renderChart({
      view: makeView({
        chart_type: 'histogram',
        measure_field: '销售额',
        bin_policy: 'auto',
      }),
    })

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    expect(option.series).toHaveLength(1)
    expect(option.series[0].type).toBe('bar')
    expect(option.series[0].barCategoryGap).toBe(0)
    expect(option.series[0].barGap).toBe(0)
    // 销售额有效值 [100,50,30,90] 合计 4 箱左右
    expect(option.series[0].data.length).toBeGreaterThanOrEqual(2)
    expect(option.xAxis.data.length).toBe(option.series[0].data.length)
  })

  it('boxplot：主 series=boxplot + 离群值 scatter，categories 来自维度分组', () => {
    // 构造有明显离群的两组数据
    const boxRows: RowResponse[] = [
      { id: 1, 月份: '2026-07-05', 销售额: 1, 团队: '研发组', 工时: 1 },
      { id: 2, 月份: '2026-08-10', 销售额: 2, 团队: '研发组', 工时: 2 },
      { id: 3, 月份: '2026-07-20', 销售额: 3, 团队: '研发组', 工时: 3 },
      { id: 4, 月份: '2026-08-15', 销售额: 4, 团队: '研发组', 工时: 4 },
      { id: 5, 月份: '2026-08-01', 销售额: 100, 团队: '研发组', 工时: 5 }, // 离群
      { id: 6, 月份: '2026-08-02', 销售额: 10, 团队: '设计组', 工时: 1 },
      { id: 7, 月份: '2026-08-03', 销售额: 20, 团队: '设计组', 工时: 2 },
      { id: 8, 月份: '2026-08-04', 销售额: 30, 团队: '设计组', 工时: 3 },
    ] as unknown as RowResponse[]

    renderChart({
      rows: boxRows,
      view: makeView({
        chart_type: 'boxplot',
        dimension_field: '团队',
        measure_field: '销售额',
      }),
    })

    const option = echartsMock.setOption.mock.calls[0][0] as Record<string, any>
    expect(option.series).toHaveLength(2)
    expect(option.series[0].type).toBe('boxplot')
    expect(option.series[1].type).toBe('scatter')
    // 两个分组的五数概括
    expect(option.series[0].data).toHaveLength(2)
    // 离群值 100 属于研发组，分组按拼音序 ['设计组', '研发组'] → 研发组索引 1
    expect(option.series[1].data).toEqual([[1, 100]])
    // xAxis.data 应为分组名（按 zh-CN 拼音序：设计组 she < 研发组 yan）
    expect(option.xAxis.data).toEqual(['设计组', '研发组'])
  })

  it('scatter 点击散点 → onRowClick 触发对应行', () => {
    const onRowClick = vi.fn()
    renderChart({
      view: makeView({
        chart_type: 'scatter',
        x_field: '工时',
        y_field: '销售额',
      }),
      onRowClick,
    })

    // echartsMock.on 被调用一次，传入 'click' + handler
    expect(echartsMock.on).toHaveBeenCalled()
    const clickHandler = echartsMock.on.mock.calls.find(([type]) => type === 'click')?.[1]
    expect(clickHandler).toBeDefined()

    // 散点第 0 点对应 ROWS 里 id=1 的行（x=1, y=100）
    clickHandler!({ seriesType: 'scatter', dataIndex: 0 })
    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
  })

  it('scatter 点击非散点系列（趋势线）不触发 onRowClick', () => {
    const onRowClick = vi.fn()
    renderChart({
      view: makeView({
        chart_type: 'scatter',
        x_field: '工时',
        y_field: '销售额',
        show_trend_line: true,
      }),
      onRowClick,
    })

    const clickHandler = echartsMock.on.mock.calls.find(([type]) => type === 'click')?.[1]
    // seriesType !== 'scatter' → 直接 return，不触发
    clickHandler!({ seriesType: 'line', dataIndex: 0 })
    expect(onRowClick).not.toHaveBeenCalled()
  })
})

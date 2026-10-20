/**
 * KlineView 组件测试 —— 行内 K 线视图.
 *
 * 覆盖：空数据空态 / 未配置字段空态 / 默认渲染（标题+最新价+列表选中+日内序列）/
 * 列表点击切换标的（标题与最新价联动 + onSelectRow 回写）/ 周线派生（x 轴聚合 + 来源脚注）/
 * 后复权无数据空态 / JSON 解析失败错误态 / 成交量开关（双 grid ↔ 单 grid）/ 搜索过滤。
 *
 * echarts/core 及子模块 mock：init 返回 fake chart，断言最后一次 setOption 的 option 结构。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import KlineView from './KlineView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, ID, RowResponse, View } from '@/api'

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
vi.mock('echarts/charts', () => ({ BarChart: {}, LineChart: {}, CandlestickChart: {} }))
vi.mock('echarts/components', () => ({
  AxisPointerComponent: {}, DataZoomComponent: {}, GridComponent: {},
  LegendComponent: {}, TooltipComponent: {},
}))
vi.mock('echarts/renderers', () => ({ SVGRenderer: {} }))

// ── 测试数据 ────────────────────────────────────────────

const FIELDS: Field[] = [
  makeField({ id: 1, name: '股票代码', field_type: 'text' }),
  makeField({ id: 2, name: '股票名称', field_type: 'text' }),
  makeField({ id: 3, name: '最新价', field_type: 'float' }),
  makeField({ id: 4, name: '涨跌幅', field_type: 'float' }),
  makeField({ id: 5, name: '成交量', field_type: 'float' }),
  makeField({ id: 6, name: '成交额', field_type: 'float' }),
  makeField({ id: 7, name: '最新交易日', field_type: 'date' }),
  makeField({ id: 8, name: '日线前复权', field_type: 'json' }),
  makeField({ id: 9, name: '日线后复权', field_type: 'json' }),
  makeField({ id: 10, name: '日线不复权', field_type: 'json' }),
  makeField({ id: 11, name: '周线前复权', field_type: 'json' }),
  makeField({ id: 12, name: '月线前复权', field_type: 'json' }),
]

/** 跨两个 ISO 周的日线 */
const DAILY = [
  { date: '2026-01-05', open: 10, close: 11, high: 11.5, low: 9.8, volume: 100, amount: 1000 },
  { date: '2026-01-06', open: 11, close: 10.5, high: 11.2, low: 10.2, volume: 200, amount: 2000 },
  { date: '2026-01-12', open: 10.5, close: 12, high: 12.5, low: 10.4, volume: 300, amount: 3000 },
]

const ROWS: RowResponse[] = [
  {
    id: 1, 股票代码: 'sh600519', 股票名称: '贵州茅台',
    最新价: 1700.5, 涨跌幅: 1.23, 成交量: 1234567, 成交额: 2.1e9, 最新交易日: '2026-01-12',
    日线前复权: JSON.stringify(DAILY), 日线后复权: null, 日线不复权: null,
  },
  {
    id: 2, 股票代码: 'sz000001', 股票名称: '平安银行',
    最新价: 11.5, 涨跌幅: -0.86, 成交量: 9e7, 成交额: 1e9, 最新交易日: '2026-01-12',
    日线前复权: JSON.stringify(DAILY.slice(0, 2)), 日线后复权: null, 日线不复权: null,
  },
  {
    id: 3, 股票代码: 'sh600000', 股票名称: '浦发银行',
    最新价: null, 涨跌幅: null, 成交量: null, 成交额: null, 最新交易日: null,
    日线前复权: '{bad json', 日线后复权: null, 日线不复权: null,
  },
] as unknown as RowResponse[]

const VIEW_OPTIONS: Record<string, unknown> = {
  symbol_field: '股票代码',
  name_field: '股票名称',
  price_field: '最新价',
  change_pct_field: '涨跌幅',
  volume_field: '成交量',
  amount_field: '成交额',
  date_field: '最新交易日',
  day_qfq_field: '日线前复权',
  day_hfq_field: '日线后复权',
  day_none_field: '日线不复权',
  week_qfq_field: '周线前复权',
  month_qfq_field: '月线前复权',
}

function makeView(viewOptions: Record<string, unknown>): View {
  return {
    id: 1, name: 'K线图', view_type: 'kline', is_default: true, view_options: viewOptions,
  } as unknown as View
}

interface RenderProps {
  rows?: RowResponse[]
  view?: View
  initialSelectedRowId?: number | null
  onSelectRow?: (id: ID) => void
}

function renderKline(props?: RenderProps) {
  return renderProviders(
    <KlineView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={props?.view ?? makeView(VIEW_OPTIONS)}
      total={props?.rows?.length ?? ROWS.length}
      initialSelectedRowId={props?.initialSelectedRowId ?? null}
      onSelectRow={props?.onSelectRow}
    />,
  )
}

/** 最后一次 setOption 的 option（纯装配结构断言） */
function lastOption(): any {
  const calls = echartsMock.setOption.mock.calls
  return calls[calls.length - 1]?.[0]
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('KlineView 空态与配置', () => {
  it('无行数据 → 引导空态', () => {
    renderKline({ rows: [] })
    expect(screen.getByTestId('kline-empty-rows')).toBeInTheDocument()
    expect(screen.queryByTestId('kline-chart-container')).not.toBeInTheDocument()
  })

  it('未配置标的字段与序列字段 → 配置空态（列出缺失项）', () => {
    renderKline({ view: makeView({ name_field: '股票名称' }) })
    const empty = screen.getByTestId('kline-empty-config')
    expect(empty.textContent).toContain('标的字段')
    expect(empty.textContent).toContain('K 线序列字段')
    expect(screen.queryByTestId('kline-chart-container')).not.toBeInTheDocument()
  })
})

describe('KlineView 渲染与交互', () => {
  it('默认选中第一只：标题/最新价/列表高亮/日线序列', () => {
    renderKline()

    expect(screen.getByTestId('kline-title').textContent).toBe('sh600519 贵州茅台')
    expect(screen.getByTestId('kline-latest-price').textContent).toContain('1700.50')
    expect(screen.getByTestId('kline-change-pct').textContent).toBe('+1.23%')

    expect(screen.getByTestId('kline-stock-1')).toHaveAttribute('data-selected', 'true')
    expect(screen.getByTestId('kline-stock-2')).toHaveAttribute('data-selected', 'false')
    expect(screen.getByTestId('kline-stock-count').textContent).toContain('共 3 只')

    const container = screen.getByTestId('kline-chart-container')
    expect(container).toHaveAttribute('data-chart-ready', 'true')

    // 日线 3 根
    expect(lastOption().xAxis[0].data).toHaveLength(3)
    expect(echartsMock.init).toHaveBeenCalledTimes(1)
  })

  it('点击第二只股票 → 标题/最新价联动并回写 onSelectRow', () => {
    const onSelectRow = vi.fn()
    renderKline({ onSelectRow })

    fireEvent.click(screen.getByTestId('kline-stock-2'))

    expect(onSelectRow).toHaveBeenCalledWith(2)
    expect(screen.getByTestId('kline-title').textContent).toBe('sz000001 平安银行')
    expect(screen.getByTestId('kline-latest-price').textContent).toContain('11.50')
    expect(screen.getByTestId('kline-change-pct').textContent).toBe('-0.86%')
    expect(screen.getByTestId('kline-stock-2')).toHaveAttribute('data-selected', 'true')
    expect(screen.getByTestId('kline-stock-1')).toHaveAttribute('data-selected', 'false')
    // 第二只日线只有 2 根
    expect(lastOption().xAxis[0].data).toHaveLength(2)

    // 图表实例复用，仅覆盖 option
    expect(echartsMock.init).toHaveBeenCalledTimes(1)
  })

  it('外部 initialSelectedRowId 生效（表格选择 → 视图选中）', () => {
    renderKline({ initialSelectedRowId: 2 })
    expect(screen.getByTestId('kline-title').textContent).toBe('sz000001 平安银行')
  })

  it('默认跳过无序列的行 → 选中第一只有数据的标的（避免打开即空态）', () => {
    const rows = [
      { id: 10, 股票代码: 'hk00700', 股票名称: '腾讯控股', 日线前复权: null },
      ROWS[0],
      ROWS[1],
    ] as unknown as RowResponse[]
    renderKline({ rows })

    expect(screen.getByTestId('kline-title').textContent).toBe('sh600519 贵州茅台')
    expect(screen.getByTestId('kline-stock-1')).toHaveAttribute('data-selected', 'true')
    expect(screen.getByTestId('kline-stock-10')).toHaveAttribute('data-selected', 'false')
    expect(screen.getByTestId('kline-chart-container')).toHaveAttribute('data-chart-ready', 'true')
  })

  it('显式选中无序列的行 → 尊重选择并给空态提示', () => {
    const rows = [
      ROWS[0],
      { id: 20, 股票代码: 'hk00700', 股票名称: '腾讯控股', 日线前复权: null },
    ] as unknown as RowResponse[]
    renderKline({ rows, initialSelectedRowId: 20 })

    expect(screen.getByTestId('kline-title').textContent).toBe('hk00700 腾讯控股')
    expect(screen.getByTestId('kline-empty-series')).toBeInTheDocument()
    expect(screen.getByTestId('kline-stock-20')).toHaveAttribute('data-selected', 'true')
  })

  it('切换周线 → 由日线派生（x 轴聚合为 2 根 + 来源脚注）', () => {
    renderKline()
    expect(lastOption().xAxis[0].data).toHaveLength(3)

    fireEvent.click(screen.getByText('周线'))

    expect(lastOption().xAxis[0].data).toEqual(['2026-01-06', '2026-01-12'])
    const source = screen.getByTestId('kline-source')
    expect(source.textContent).toContain('周线前复权')
    expect(source.textContent).toContain('派生')
  })

  it('切换后复权（该口径无数据）→ 序列空态提示', () => {
    renderKline()

    fireEvent.click(screen.getByText('后复权'))

    expect(screen.getByTestId('kline-empty-series').textContent).toContain('日线后复权暂无数据')
    expect(screen.getByTestId('kline-chart-container')).toHaveAttribute('data-chart-ready', 'false')
    expect(screen.queryByTestId('kline-error')).not.toBeInTheDocument()
  })

  it('JSON 解析失败 → 错误态（不崩溃，展示字段与原因）', () => {
    renderKline({ rows: [ROWS[2]] })

    const err = screen.getByTestId('kline-error')
    expect(err.textContent).toContain('日线前复权暂无数据')
    expect(err.textContent).toContain('解析失败')
    expect(screen.getByTestId('kline-chart-container')).toHaveAttribute('data-chart-ready', 'false')
  })

  it('关闭成交量 → 单 grid（价格占满）', () => {
    renderKline()
    expect(lastOption().grid).toHaveLength(2)

    fireEvent.click(screen.getByTestId('kline-toggle-volume'))

    expect(lastOption().grid).toHaveLength(1)
    expect(lastOption().xAxis).toHaveLength(1)
  })

  it('搜索过滤列表（不影响已选标的图表）', () => {
    renderKline()

    fireEvent.change(screen.getByPlaceholderText('搜索代码 / 名称'), { target: { value: '平安' } })

    expect(screen.queryByTestId('kline-stock-1')).not.toBeInTheDocument()
    expect(screen.getByTestId('kline-stock-2')).toBeInTheDocument()
    expect(screen.getByTestId('kline-title').textContent).toBe('sh600519 贵州茅台')

    fireEvent.change(screen.getByPlaceholderText('搜索代码 / 名称'), { target: { value: '不存在' } })
    expect(screen.getByText('没有匹配的标的')).toBeInTheDocument()
  })
})

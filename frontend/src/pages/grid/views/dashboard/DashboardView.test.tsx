/** DashboardView 只读画布测试（ADR 0023 P0）.
 *
 * 覆盖：seed 同款一屏渲染（KPI/图表/文本/明细）/ 非法配置定位空态 / 空画布 / 加载与错误态 /
 * 窄屏单列塌陷。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import type { Field, RowResponse, View } from '@/api'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import DashboardView from './DashboardView'

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

const FIELDS: Field[] = [
  makeField({ id: 1, name: '订单号', field_type: 'text' }),
  makeField({ id: 2, name: '商品类别', field_type: 'text' }),
  makeField({ id: 3, name: '销售额', field_type: 'number' }),
  makeField({ id: 4, name: '日期', field_type: 'date' }),
]

const ROWS: RowResponse[] = [
  { id: 1, 订单号: 'A001', 商品类别: '数码', 销售额: 100, 日期: '2026-01-10' },
  { id: 2, 订单号: 'A002', 商品类别: '家电', 销售额: 50, 日期: '2026-02-11' },
  { id: 3, 订单号: 'A003', 商品类别: '数码', 销售额: 30, 日期: '2026-03-12' },
] as unknown as RowResponse[]

const CONFIG = {
  schema_version: 1,
  canvas: { cols: 12, row_height: 40, gap: 12, padding: 16 },
  widgets: [
    {
      id: 'kpi-count', type: 'kpi', title: '订单总数',
      layout: { x: 0, y: 0, w: 3, h: 4 },
      kpi: { value: { field: '订单号', agg: 'count' } },
    },
    {
      id: 'kpi-sales', type: 'kpi', title: '销售额合计',
      layout: { x: 3, y: 0, w: 3, h: 4 },
      kpi: { value: { field: '销售额', agg: 'sum' } },
    },
    {
      id: 'sales-chart', type: 'chart', title: '类目销售额',
      layout: { x: 0, y: 4, w: 6, h: 10 },
      chart: { type: 'bar', x: '商品类别', y: ['销售额'], agg: 'sum' },
    },
    {
      id: 'note', type: 'text', title: '口径说明',
      layout: { x: 6, y: 4, w: 6, h: 4 },
      text: { content: '销售额按订单金额汇总。' },
    },
    {
      id: 'detail', type: 'table', title: '订单明细',
      layout: { x: 6, y: 8, w: 6, h: 6 },
      table: { columns: ['订单号', '销售额'], row_limit: 2 },
    },
  ],
  global_filters: [],
  settings: { refresh_interval: 0, theme: 'inherit' },
}

function makeView(view_options: Record<string, unknown>): View {
  return { id: 1, name: '销售画布', view_type: 'dashboard', is_default: false, view_options } as unknown as View
}

function renderDashboard(opts?: {
  view_options?: Record<string, unknown>
  rows?: RowResponse[]
  loading?: boolean
  error?: string | null
}) {
  return renderProviders(
    <DashboardView
      rows={opts?.rows ?? ROWS}
      fields={FIELDS}
      view={makeView(opts?.view_options ?? CONFIG)}
      loading={opts?.loading}
      error={opts?.error}
    />,
  )
}

describe('DashboardView', () => {
  it('渲染四类组件与画布栅格', () => {
    renderDashboard()
    expect(screen.getByTestId('dashboard-canvas')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-kpi-value-kpi-count')).toHaveTextContent('3')
    expect(screen.getByTestId('dashboard-kpi-value-kpi-sales')).toHaveTextContent('180')
    expect(screen.getByTestId('dashboard-text-note')).toHaveTextContent('销售额按订单金额汇总。')
    expect(screen.getByTestId('dashboard-table-detail')).toBeInTheDocument()
    // row_limit=2 只渲染前两行
    expect(screen.getByTestId('dashboard-table-detail')).not.toHaveTextContent('A003')
    expect(screen.getByTestId('chart-container')).toHaveAttribute('data-chart-ready', 'true')
  })

  it('组件级 query 过滤在本地生效', () => {
    const config = {
      ...CONFIG,
      widgets: [{
        ...CONFIG.widgets[1],
        query: { filters: [{ field_name: '商品类别', op: 'eq', value: '数码' }] },
      }],
    }
    renderDashboard({ view_options: config })
    expect(screen.getByTestId('dashboard-kpi-value-kpi-sales')).toHaveTextContent('130')
  })

  it('非法配置显示可定位空态而不是炸整页', () => {
    renderDashboard({
      view_options: {
        widgets: [{
          id: 'bad', type: 'chart', layout: { x: 0, y: 0, w: 6, h: 8 },
          chart: { type: 'bar', x: '商品类别', y: ['订单号'], agg: 'sum' },
        }],
      },
    })
    expect(screen.getByTestId('dashboard-config-error')).toHaveTextContent('widgets[0].chart.y[0]')
  })

  it('空画布显示引导空态', () => {
    renderDashboard({ view_options: { widgets: [] } })
    expect(screen.getByTestId('dashboard-empty')).toBeInTheDocument()
  })

  it('加载态覆盖组件内容', () => {
    renderDashboard({ loading: true })
    expect(screen.getByTestId('dashboard-widget-kpi-sales-loading')).toBeInTheDocument()
  })

  it('错误态覆盖组件内容', () => {
    renderDashboard({ error: '数据加载失败，请稍后重试' })
    expect(screen.getByTestId('dashboard-widget-kpi-sales-error')).toHaveTextContent('数据加载失败')
  })

  it('窄屏按单列塌陷（每块占满 12 列）', () => {
    const original = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 500 })
    renderDashboard()
    const wrappers = screen.getByTestId('dashboard-canvas').children
    expect((wrappers[0] as HTMLElement).style.gridColumn).toBe('1 / span 12')
    fireEvent(window, new Event('resize'))
    expect((wrappers[0] as HTMLElement).style.gridColumn).toBe('1 / span 12')
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: original })
  })

  it('空数据时非文本组件显示空态', () => {
    renderDashboard({ rows: [] })
    expect(screen.getByTestId('dashboard-widget-kpi-sales-empty')).toBeInTheDocument()
    // 文本组件不因无数据隐藏
    expect(screen.queryByTestId('dashboard-widget-note-empty')).not.toBeInTheDocument()
  })
})

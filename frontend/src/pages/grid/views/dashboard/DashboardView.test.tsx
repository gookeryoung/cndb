/** DashboardView 只读画布测试（ADR 0023 P0）.
 *
 * 覆盖：seed 同款一屏渲染（KPI/图表/文本/明细）/ 非法配置定位空态 / 空画布 / 加载与错误态 /
 * 窄屏单列塌陷。
 * P1：编辑入口与权限、键盘微调、撤销/重做、属性面板新增、显式保存、Ctrl+S、Esc 回滚。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
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
  RadarChart: {}, FunnelChart: {}, GaugeChart: {}, HeatmapChart: {}, TreemapChart: {},
}))
vi.mock('echarts/components', () => ({
  GridComponent: {}, TooltipComponent: {}, LegendComponent: {},
  RadarComponent: {}, VisualMapComponent: {},
}))
vi.mock('echarts/renderers', () => ({ SVGRenderer: {} }))

const dashboardData = vi.hoisted(() => vi.fn())
vi.mock('@/api/views', () => ({ viewApi: { dashboardData } }))

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
  canEdit?: boolean
  onSave?: (options: Record<string, unknown>) => void
  total?: number
  workspaceId?: string | number
  tableId?: string | number
}) {
  return renderProviders(
    <DashboardView
      rows={opts?.rows ?? ROWS}
      fields={FIELDS}
      view={makeView(opts?.view_options ?? CONFIG)}
      loading={opts?.loading}
      error={opts?.error}
      canEdit={opts?.canEdit}
      onSave={opts?.onSave}
      total={opts?.total}
      workspaceId={opts?.workspaceId ?? 1}
      tableId={opts?.tableId ?? 2}
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
    expect(screen.getByTestId('dashboard-chart-container-sales-chart')).toHaveAttribute('data-chart-ready', 'true')
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

describe('DashboardView 服务端取数路径（大表）', () => {
  it('只提交数据 widget，渲染口径提示与单卡错误', async () => {
    dashboardData.mockResolvedValue({
      items: [
        {
          widget_id: 'kpi-count',
          dataset: { kind: 'kpi', field: '订单号', agg: 'count', value: 12000 },
          meta: { scanned: 20000, total: 12000, truncated: false, cached: false },
        },
        {
          widget_id: 'kpi-sales',
          dataset: { kind: 'kpi', field: '销售额', agg: 'sum', value: 9 },
          meta: { scanned: 20000, total: 12000, truncated: false, cached: true },
        },
        {
          widget_id: 'sales-chart',
          dataset: { kind: 'category', categories: ['数码'], series: [{ name: '销售额', data: [180] }] },
          meta: { scanned: 20000, total: 12000, truncated: false, cached: false },
        },
      ],
      errors: [{ widget_id: 'detail', detail: '明细取数失败' }],
    })
    renderDashboard({ total: 12000 })

    await waitFor(() => expect(dashboardData).toHaveBeenCalledTimes(1))
    // 文本卡片不参与取数
    expect(dashboardData.mock.calls[0][3]).toEqual({
      widget_ids: ['kpi-count', 'kpi-sales', 'sales-chart', 'detail'],
    })

    await waitFor(() => expect(screen.getByTestId('dashboard-widget-kpi-sales-meta'))
      .toHaveTextContent('样本 20000 / 总行数 12000 · 缓存'))
    expect(screen.getByTestId('dashboard-kpi-value-kpi-sales')).toHaveTextContent('9')
    expect(screen.getByTestId('dashboard-chart-container-sales-chart')).toHaveAttribute('data-chart-ready', 'true')
    expect(screen.getByTestId('dashboard-widget-detail-error')).toHaveTextContent('明细取数失败')
  })
})

const EDIT_CONFIG = {
  schema_version: 1,
  canvas: { cols: 12, row_height: 40, gap: 12, padding: 16 },
  widgets: [{
    id: 'k1', type: 'kpi', title: '订单总数',
    layout: { x: 0, y: 0, w: 3, h: 4 },
    kpi: { value: { field: '订单号', agg: 'count' } },
  }],
  global_filters: [],
  settings: { refresh_interval: 0, theme: 'inherit' },
}

/** 进入编辑态并等待工具栏切换 */
async function enterEditing() {
  fireEvent.click(screen.getByTestId('dashboard-edit'))
  return screen.findByTestId('dashboard-save')
}

describe('DashboardView P1 编辑态', () => {
  it('无编辑权限时不渲染工具栏', () => {
    renderDashboard({ view_options: EDIT_CONFIG })
    expect(screen.queryByTestId('dashboard-toolbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-edit')).not.toBeInTheDocument()
  })

  it('canEdit 显示编辑入口，进入后出现保存/退出与操作提示', async () => {
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    expect(screen.getByTestId('dashboard-edit')).toBeInTheDocument()
    await enterEditing()
    expect(screen.getByTestId('dashboard-edit-hint')).toHaveTextContent('方向键微调')
    expect(screen.getByTestId('dashboard-widget-k1-drag-handle')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-resize-k1')).toBeInTheDocument()
  })

  it('方向键平移、Shift+方向键缩放', async () => {
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    await enterEditing()
    const card = screen.getByTestId('dashboard-card-k1')
    expect(card.style.gridColumn).toBe('1 / span 3')
    fireEvent.keyDown(card, { key: 'ArrowRight' })
    await waitFor(() => expect(card.style.gridColumn).toBe('2 / span 3'))
    fireEvent.keyDown(card, { key: 'ArrowRight', shiftKey: true })
    await waitFor(() => expect(card.style.gridColumn).toBe('2 / span 4'))
  })

  it('撤销 / 重做回退布局变更', async () => {
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    await enterEditing()
    const card = screen.getByTestId('dashboard-card-k1')
    fireEvent.keyDown(card, { key: 'ArrowRight' })
    await waitFor(() => expect(card.style.gridColumn).toBe('2 / span 3'))
    expect(screen.getByTestId('dashboard-undo')).toBeEnabled()

    fireEvent.click(screen.getByTestId('dashboard-undo'))
    await waitFor(() => expect(card.style.gridColumn).toBe('1 / span 3'))
    expect(screen.getByTestId('dashboard-redo')).toBeEnabled()

    fireEvent.click(screen.getByTestId('dashboard-redo'))
    await waitFor(() => expect(card.style.gridColumn).toBe('2 / span 3'))
  })

  it('属性面板添加组件后新块出现在画布', async () => {
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    await enterEditing()
    fireEvent.click(screen.getByTestId('dashboard-properties'))
    fireEvent.click(await screen.findByTestId('dashboard-drawer-add'))
    expect(await screen.findByTestId('dashboard-card-w_chart_1')).toBeInTheDocument()
    expect(screen.getByText('有未保存修改')).toBeInTheDocument()
  })

  it('保存回调携带最新布局并退出编辑态', async () => {
    const onSave = vi.fn()
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true, onSave })
    await enterEditing()
    fireEvent.keyDown(screen.getByTestId('dashboard-card-k1'), { key: 'ArrowRight' })
    expect(await screen.findByText('有未保存修改')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('dashboard-save'))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    const options = onSave.mock.calls[0][0] as Record<string, unknown>
    const widgets = options.widgets as Array<{ id: string; layout: { x: number } }>
    expect(widgets[0].layout.x).toBe(1)
    // 退出编辑态
    expect(screen.queryByTestId('dashboard-save')).not.toBeInTheDocument()
    expect(screen.getByTestId('dashboard-edit')).toBeInTheDocument()
  })

  it('Ctrl+S 触发保存', async () => {
    const onSave = vi.fn()
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true, onSave })
    await enterEditing()
    fireEvent.keyDown(screen.getByTestId('dashboard-card-k1'), { key: 'ArrowDown' })
    fireEvent.keyDown(window, { key: 's', ctrlKey: true })
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
  })

  it('Esc 无未保存变更时直接退出编辑', async () => {
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    await enterEditing()
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('dashboard-save')).not.toBeInTheDocument())
  })

  it('Esc 有未保存变更时弹出放弃确认，确认后回滚', async () => {
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    await enterEditing()
    fireEvent.keyDown(screen.getByTestId('dashboard-card-k1'), { key: 'ArrowRight' })
    expect(await screen.findByText('有未保存修改')).toBeInTheDocument()
    // 方向键微调会选中并打开属性面板（面板按需懒加载）；先关闭面板，Esc 才作用于退出编辑
    await waitFor(() => expect(document.querySelector('.ant-drawer-close')).toBeInTheDocument())
    fireEvent.click(document.querySelector('.ant-drawer-close') as HTMLElement)
    await waitFor(() => expect(document.querySelector('.ant-drawer-close')).not.toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'Escape' })
    // antd 6 的 Modal 会同时渲染可见标题与无障碍标题，故用 findAll
    expect((await screen.findAllByText('放弃未保存的画布修改？')).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: '放弃修改' }))
    await waitFor(() => expect(screen.queryByTestId('dashboard-save')).not.toBeInTheDocument())
    // 回滚到基线布局
    expect(screen.getByTestId('dashboard-card-k1').style.gridColumn).toBe('1 / span 3')
  })

  it('窄屏下禁用编辑入口', () => {
    const original = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 500 })
    renderDashboard({ view_options: EDIT_CONFIG, canEdit: true })
    expect(screen.getByTestId('dashboard-edit')).toBeDisabled()
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: original })
  })
})

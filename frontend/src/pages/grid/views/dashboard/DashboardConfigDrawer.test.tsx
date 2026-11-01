/** Dashboard 属性面板测试（ADR 0023 P1）.
 *
 * 覆盖：布局段（选中组件 / 坐标输入 / 删除 / 预设 / 添加）· 数据段（图表 / 文本）·
 * 外观段（标题 / 画布参数 / 主题）。面板只回调，不直接改配置。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import type { Field } from '@/api'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import DashboardConfigDrawer from './DashboardConfigDrawer'
import type { DashboardConfig, DashboardWidget } from './dashboardModel'

/** 数据来源表候选 / 目标表字段（P3 跨表，ADR 0023 D8） */
const tableListMock = vi.hoisted(() => vi.fn())
const fieldListMock = vi.hoisted(() => vi.fn())
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, tableApi: { list: tableListMock }, fieldApi: { list: fieldListMock } }
})

const FIELDS: Field[] = [
  makeField({ id: 1, name: '商品类别', field_type: 'text' }),
  makeField({ id: 2, name: '销售额', field_type: 'number' }),
  makeField({ id: 3, name: '日期', field_type: 'date' }),
]

function makeWidget(id: string, type: 'text' | 'chart', x = 0): DashboardWidget {
  const base = {
    id,
    type,
    title: `标题-${id}`,
    layout: { id, x, y: 0, w: 6, h: 4 },
    query: { filters: [], filter_logic: 'AND' as const, sortings: [] },
  }
  if (type === 'chart') {
    return {
      ...base,
      type: 'chart',
      chart: {
        type: 'bar', x: '商品类别', y: ['销售额'], agg: 'sum',
        stack: 'none', sort: 'none', dual_axis: false, format: {},
      },
    }
  }
  return { ...base, type: 'text', text: { content: '说明文本' } }
}

const CONFIG: DashboardConfig = {
  schema_version: 1,
  canvas: { cols: 12, row_height: 40, gap: 12, padding: 16 },
  widgets: [makeWidget('a', 'text', 0), makeWidget('b', 'chart', 6)],
  global_filters: [],
  settings: { refresh_interval: 0, theme: 'inherit' },
}

function renderDrawer(overrides?: {
  open?: boolean
  selectedId?: string | null
  fields?: Field[]
  config?: DashboardConfig
  workspaceId?: string | number
  baseTableId?: string | number
}) {
  const handlers = {
    onClose: vi.fn(),
    onSelect: vi.fn(),
    onPatchWidget: vi.fn(),
    onPatchLayout: vi.fn(),
    onRemoveWidget: vi.fn(),
    onAddWidget: vi.fn(),
    onApplyPreset: vi.fn(),
    onUpdateCanvas: vi.fn(),
    onUpdateSettings: vi.fn(),
  }
  renderProviders(
    <DashboardConfigDrawer
      open={overrides?.open ?? true}
      config={overrides?.config ?? CONFIG}
      fields={overrides?.fields ?? FIELDS}
      workspaceId={overrides?.workspaceId}
      baseTableId={overrides?.baseTableId}
      selectedId={overrides?.selectedId === undefined ? 'a' : overrides.selectedId}
      {...handlers}
    />,
  )
  return handlers
}

describe('DashboardConfigDrawer', () => {
  it('open=false 时不渲染面板内容', () => {
    renderDrawer({ open: false })
    expect(screen.queryByText('画布属性')).not.toBeInTheDocument()
  })

  it('布局段：选择组件触发 onSelect', async () => {
    const { onSelect } = renderDrawer()
    fireEvent.mouseDown(document.querySelectorAll('.ant-drawer .ant-select')[0])
    fireEvent.click(await screen.findByText('标题-b', { selector: '.ant-select-item-option-content' }))
    expect(onSelect).toHaveBeenCalledWith('b')
  })

  it('布局段：修改 X 坐标触发 onPatchLayout', () => {
    const { onPatchLayout } = renderDrawer()
    const inputs = screen.getAllByRole('spinbutton')
    fireEvent.change(inputs[0], { target: { value: '3' } })
    expect(onPatchLayout).toHaveBeenCalledWith('a', { x: 3 })
  })

  it('布局段：删除当前组件触发 onRemoveWidget', () => {
    const { onRemoveWidget } = renderDrawer()
    fireEvent.click(screen.getByTestId('dashboard-drawer-remove'))
    expect(onRemoveWidget).toHaveBeenCalledWith('a')
  })

  it('布局段：5 个预设按钮逐个触发 onApplyPreset', () => {
    const { onApplyPreset } = renderDrawer()
    const keys = ['single', 'two', 'main-side', 'grid-2x2', 'kpi-charts']
    // antd 会在两个汉字之间自动加空格（如「单 栏」），故用正则匹配
    const labels = [/单\s*栏/, '两栏等分', '主次（8+4）', '2×2', 'KPI 条 + 图表']
    labels.forEach((label, i) => {
      fireEvent.click(screen.getByRole('button', { name: label }))
      expect(onApplyPreset).toHaveBeenLastCalledWith(keys[i])
    })
  })

  it('布局段：添加组件按当前类型触发 onAddWidget', () => {
    const { onAddWidget } = renderDrawer()
    fireEvent.click(screen.getByTestId('dashboard-drawer-add'))
    expect(onAddWidget).toHaveBeenCalledWith('chart')
  })

  it('布局段：无字段时禁用添加入口', () => {
    renderDrawer({ fields: [] })
    expect(screen.getByTestId('dashboard-drawer-add')).toBeDisabled()
  })

  it('数据段：文本组件编辑内容触发 onPatchWidget', async () => {
    const { onPatchWidget } = renderDrawer()
    fireEvent.click(screen.getByRole('tab', { name: '数据' }))
    const textarea = await screen.findByTestId('dashboard-text-content')
    fireEvent.change(textarea, { target: { value: '新说明' } })
    expect(onPatchWidget).toHaveBeenCalledWith('a', expect.any(Function))
    const updater = onPatchWidget.mock.calls[0][1] as (w: DashboardWidget) => DashboardWidget
    expect(updater(CONFIG.widgets[0])).toMatchObject({ text: { content: '新说明' } })
  })

  it('数据段：图表组件渲染类型 / X / 度量字段', async () => {
    renderDrawer({ selectedId: 'b' })
    fireEvent.click(screen.getByRole('tab', { name: '数据' }))
    expect(await screen.findByText('柱状图')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-chart-x')).toBeInTheDocument()
    expect(screen.getByTestId('dashboard-chart-y')).toBeInTheDocument()
  })

  it('数据段：未选中组件显示引导空态', async () => {
    renderDrawer({ selectedId: null })
    fireEvent.click(screen.getByRole('tab', { name: '数据' }))
    expect(await screen.findByText(/先在/)).toBeInTheDocument()
  })

  it('外观段：修改标题触发 onPatchWidget 并写回 title', () => {
    const { onPatchWidget } = renderDrawer()
    fireEvent.click(screen.getByRole('tab', { name: '外观' }))
    fireEvent.change(screen.getByTestId('dashboard-widget-title'), { target: { value: '新标题' } })
    expect(onPatchWidget).toHaveBeenCalledWith('a', expect.any(Function))
    const updater = onPatchWidget.mock.calls[0][1] as (w: DashboardWidget) => DashboardWidget
    expect(updater(CONFIG.widgets[0]).title).toBe('新标题')
  })

  it('外观段：画布行高 / 间距 / 内边距触发 onUpdateCanvas', () => {
    const { onUpdateCanvas } = renderDrawer()
    fireEvent.click(screen.getByRole('tab', { name: '外观' }))
    const inputs = screen.getAllByRole('spinbutton')
    fireEvent.change(inputs[0], { target: { value: '48' } })
    fireEvent.change(inputs[1], { target: { value: '8' } })
    fireEvent.change(inputs[2], { target: { value: '24' } })
    expect(onUpdateCanvas).toHaveBeenCalledWith({ row_height: 48 })
    expect(onUpdateCanvas).toHaveBeenCalledWith({ gap: 8 })
    expect(onUpdateCanvas).toHaveBeenCalledWith({ padding: 24 })
  })

  it('外观段：主题切换触发 onUpdateSettings', async () => {
    const { onUpdateSettings } = renderDrawer()
    fireEvent.click(screen.getByRole('tab', { name: '外观' }))
    // 布局段仍挂载（含组件选择 / 添加类型 2 个 Select），主题 Select 为最后一个
    const selects = document.querySelectorAll('.ant-drawer .ant-select')
    fireEvent.mouseDown(selects[selects.length - 1])
    fireEvent.click(await screen.findByText('深色', { selector: '.ant-select-item-option-content' }))
    expect(onUpdateSettings).toHaveBeenCalledWith({ theme: 'dark' })
  })
})

/** 跨表 chart widget（目标表 id=9） */
function makeCrossConfig(): DashboardConfig {
  const chart = makeWidget('c', 'chart', 0)
  return {
    ...CONFIG,
    widgets: [
      CONFIG.widgets[0],
      { ...chart, title: '跨表图', query: { ...chart.query, table_id: 9 } } as DashboardWidget,
    ],
  }
}

const TABLES = [{ id: 2, name: '订单表' }, { id: 9, name: '客户表' }]

describe('DashboardConfigDrawer P3 数据来源表', () => {
  it('候选表排除基表并标记当前表', async () => {
    tableListMock.mockResolvedValue(TABLES)
    renderDrawer({ selectedId: 'b', workspaceId: 1, baseTableId: 2 })
    fireEvent.click(screen.getByRole('tab', { name: '数据' }))
    const select = await screen.findByTestId('dashboard-source-table')
    await waitFor(() => expect(tableListMock).toHaveBeenCalledWith(1))
    fireEvent.mouseDown(select)
    expect(await screen.findByText('当前表订单表', { selector: '.ant-select-item-option-content' }))
      .toBeInTheDocument()
    expect(screen.getByText('客户表', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
  })

  it('切换到目标表按该表字段重建数据段并写回 table_id', async () => {
    tableListMock.mockResolvedValue(TABLES)
    fieldListMock.mockResolvedValue([
      makeField({ id: 11, name: '客户', field_type: 'text' }),
      makeField({ id: 12, name: '合同额', field_type: 'number' }),
    ])
    const { onPatchWidget } = renderDrawer({ selectedId: 'b', workspaceId: 1, baseTableId: 2 })
    fireEvent.click(screen.getByRole('tab', { name: '数据' }))
    const select = await screen.findByTestId('dashboard-source-table')
    await waitFor(() => expect(tableListMock).toHaveBeenCalledWith(1))
    fireEvent.mouseDown(select)
    fireEvent.click(await screen.findByText('客户表', { selector: '.ant-select-item-option-content' }))

    await waitFor(() => expect(fieldListMock).toHaveBeenCalledWith(1, 9))
    await waitFor(() => expect(onPatchWidget).toHaveBeenCalled())
    const updater = onPatchWidget.mock.calls[0][1] as (w: DashboardWidget) => DashboardWidget
    const next = updater(CONFIG.widgets[1])
    expect(next.type).toBe('chart')
    if (next.type !== 'chart') throw new Error('期望 chart widget')
    expect(next.query.table_id).toBe(9)
    expect(next.title).toBe('标题-b')
    expect(next.chart.x).toBe('客户')
    expect(next.chart.y).toEqual(['合同额'])
  })

  it('切回基表删除 table_id 并复用基表字段', async () => {
    tableListMock.mockResolvedValue(TABLES)
    fieldListMock.mockResolvedValue([makeField({ id: 11, name: '合同额', field_type: 'number' })])
    const { onPatchWidget } = renderDrawer({
      config: makeCrossConfig(), selectedId: 'c', workspaceId: 1, baseTableId: 2,
    })
    fireEvent.click(screen.getByRole('tab', { name: '数据' }))
    const select = await screen.findByTestId('dashboard-source-table')
    await waitFor(() => expect(fieldListMock).toHaveBeenCalledWith(1, 9))
    await waitFor(() => expect(select).not.toBeDisabled())
    fireEvent.mouseDown(select)
    fireEvent.click(await screen.findByText(/当前表/, { selector: '.ant-select-item-option-content' }))

    await waitFor(() => expect(onPatchWidget).toHaveBeenCalled())
    const updater = onPatchWidget.mock.calls[0][1] as (w: DashboardWidget) => DashboardWidget
    const next = updater(makeCrossConfig().widgets[1])
    expect(next.query.table_id).toBeUndefined()
    expect(next.type).toBe('chart')
    if (next.type !== 'chart') throw new Error('期望 chart widget')
    expect(next.chart.x).toBe('商品类别')
    expect(next.chart.y).toEqual(['销售额'])
  })
})

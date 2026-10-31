/** dashboard ECharts 按需注册测试（ADR 0023 P2）.
 *
 * 覆盖：首次调用注册 14 类图所需模块，重复调用幂等（不重复 use）。
 */

import { describe, expect, it, vi } from 'vitest'

const useMock = vi.hoisted(() => vi.fn())
vi.mock('echarts/core', () => ({ use: useMock }))
vi.mock('echarts/charts', () => ({
  BarChart: {}, LineChart: {}, PieChart: {}, ScatterChart: {}, BoxplotChart: {},
  RadarChart: {}, FunnelChart: {}, GaugeChart: {}, HeatmapChart: {}, TreemapChart: {},
}))
vi.mock('echarts/components', () => ({
  GridComponent: {}, TooltipComponent: {}, LegendComponent: {},
  RadarComponent: {}, VisualMapComponent: {},
}))
vi.mock('echarts/renderers', () => ({ SVGRenderer: {} }))

describe('registerDashboardCharts', () => {
  it('注册一次后重复调用不再 use', async () => {
    const { registerDashboardCharts } = await import('./register')
    registerDashboardCharts()
    expect(useMock).toHaveBeenCalledTimes(1)
    const modules = useMock.mock.calls[0][0] as unknown[]
    // 10 类图 + 5 个组件 + 1 个 renderer
    expect(modules).toHaveLength(16)
    registerDashboardCharts()
    expect(useMock).toHaveBeenCalledTimes(1)
  })
})

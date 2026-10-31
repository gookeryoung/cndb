/** dashboard 图表画布测试（ADR 0023 P2）.
 *
 * 覆盖 ECharts 生命周期：init / setOption(notMerge) / ResizeObserver resize /
 * getDataURL 导出 / onSeriesClick 透传 / 卸载 dispose 容错。
 */

import { createRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import ChartCanvas, { type ChartCanvasHandle } from './ChartCanvas'

const echartsMock = vi.hoisted(() => {
  const setOption = vi.fn()
  const on = vi.fn()
  const resize = vi.fn()
  const dispose = vi.fn()
  const getDataURL = vi.fn(() => 'data:image/png;base64,AAA')
  const init = vi.fn(() => ({ setOption, on, resize, dispose, getDataURL }))
  return { init, setOption, on, resize, dispose, getDataURL }
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

describe('ChartCanvas', () => {
  it('初始化并设置 option（notMerge）', () => {
    const option = { series: [{ type: 'bar', data: [1, 2] }] }
    render(<ChartCanvas option={option} testId="canvas" />)
    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect((echartsMock.init.mock.calls[0] as unknown[])[2]).toEqual({ renderer: 'svg' })
    expect(echartsMock.setOption).toHaveBeenCalledWith(option, true)
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-chart-ready', 'true')
  })

  it('无 option 时展示空态覆盖层且容器隐藏', () => {
    render(<ChartCanvas option={null} empty={<span>暂无数据</span>} testId="canvas" />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
    const el = screen.getByTestId('canvas')
    expect(el).toHaveAttribute('data-chart-ready', 'false')
    expect(echartsMock.setOption).not.toHaveBeenCalled()
  })

  it('getDataURL 导出 PNG，无实例时返回 null', () => {
    const ref = createRef<ChartCanvasHandle>()
    const { unmount } = render(<ChartCanvas ref={ref} option={{}} testId="canvas" />)
    expect(ref.current?.getDataURL()).toBe('data:image/png;base64,AAA')
    expect(echartsMock.getDataURL).toHaveBeenCalledWith({ type: 'png', pixelRatio: 2 })
    const handle = ref.current!
    unmount()
    expect(handle.getDataURL()).toBeNull()
  })

  it('ResizeObserver 触发 resize', () => {
    let cb: (() => void) | undefined
    class RO {
      constructor(fn: () => void) { cb = fn }
      observe = vi.fn()
      disconnect = vi.fn()
    }
    const original = globalThis.ResizeObserver
    Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, writable: true, value: RO })
    try {
      render(<ChartCanvas option={{}} testId="canvas" />)
      act(() => { cb?.() })
      expect(echartsMock.resize).toHaveBeenCalled()
    } finally {
      Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, writable: true, value: original })
    }
  })

  it('点击事件透传 seriesType / dataIndex', () => {
    const onSeriesClick = vi.fn()
    render(<ChartCanvas option={{}} onSeriesClick={onSeriesClick} testId="canvas" />)
    const handler = echartsMock.on.mock.calls.at(-1)?.[1] as (params: unknown) => void
    handler({ seriesType: 'bar', dataIndex: 3 })
    expect(onSeriesClick).toHaveBeenCalledWith({ seriesType: 'bar', dataIndex: 3 })
    handler({ seriesType: undefined, dataIndex: 'x' })
    expect(onSeriesClick).toHaveBeenLastCalledWith({ seriesType: undefined, dataIndex: undefined })
  })

  it('卸载时 disconnect 并 dispose（dispose 抛错不阻断卸载）', () => {
    echartsMock.dispose.mockImplementation(() => { throw new Error('already removed') })
    const onSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = render(<ChartCanvas option={{}} testId="canvas" />)
    expect(() => unmount()).not.toThrow()
    expect(echartsMock.dispose).toHaveBeenCalled()
    onSpy.mockRestore()
  })
})

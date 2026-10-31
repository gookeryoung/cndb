/** dashboard 图表画布：ECharts 生命周期与导出（ADR 0023 P2）.
 *
 * 约束（沿用 ChartCard 的教训）：ECharts dispose 会清空容器 DOM，
 * 因此图表容器**不得承载 React 子节点**，空态用兄弟覆盖层呈现。
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, type ReactNode } from 'react'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import { registerDashboardCharts } from './register'

export interface ChartCanvasHandle {
  /** 导出 PNG dataURL（无实例时返回 null） */
  getDataURL: () => string | null
}

export interface ChartCanvasProps {
  option: EChartsCoreOption | null
  /** 无 option 时展示的覆盖层（兄弟节点，不进图表容器） */
  empty?: ReactNode
  onSeriesClick?: (params: { seriesType?: string; dataIndex?: number }) => void
  testId?: string
}

const ChartCanvas = forwardRef<ChartCanvasHandle, ChartCanvasProps>(function ChartCanvas(
  { option, empty, onSeriesClick, testId = 'dashboard-chart-container' },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const clickRef = useRef(onSeriesClick)
  clickRef.current = onSeriesClick

  useEffect(() => {
    if (!containerRef.current) return
    registerDashboardCharts()
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    chart.on('click', (params) => {
      clickRef.current?.({
        seriesType: typeof params.seriesType === 'string' ? params.seriesType : undefined,
        dataIndex: typeof params.dataIndex === 'number' ? params.dataIndex : undefined,
      })
    })
    const ro = new ResizeObserver(() => chartRef.current?.resize())
    ro.observe(containerRef.current)
    return () => {
      ro.disconnect()
      try {
        chart.dispose()
      } catch {
        // 宿主可能已整体卸载/清空容器，dispose 内的 removeChild 不应阻断卸载
      }
      chartRef.current = null
    }
  }, [])

  // notMerge：类型 / 系列数变化时彻底替换，防旧系列残留
  useEffect(() => {
    if (!chartRef.current || !option) return
    chartRef.current.setOption(option, true)
  }, [option])

  const getDataURL = useCallback((): string | null => {
    if (!chartRef.current) return null
    return chartRef.current.getDataURL({ type: 'png', pixelRatio: 2 })
  }, [])

  useImperativeHandle(ref, () => ({ getDataURL }), [getDataURL])

  return (
    <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex' }}>
      <div
        ref={containerRef}
        data-testid={testId}
        data-chart-ready={option ? 'true' : 'false'}
        style={{
          flex: 1,
          minWidth: 0,
          visibility: option ? 'visible' : 'hidden',
          pointerEvents: option ? 'auto' : 'none',
        }}
      />
      {!option && empty && (
        <div
          style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
          }}
        >
          {empty}
        </div>
      )}
    </div>
  )
})

export default ChartCanvas

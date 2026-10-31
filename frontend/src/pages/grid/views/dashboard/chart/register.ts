/** dashboard 按需注册 ECharts 模块（ADR 0023 P2）.
 *
 * 只有 dashboard 图表 chunk 引入本模块，避免把 14 类图全部塞进主入口；
 * `ChartCanvas` 初始化前调用一次，重复调用无副作用。
 */

import * as echarts from 'echarts/core'
import {
  BarChart,
  BoxplotChart,
  FunnelChart,
  GaugeChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  TreemapChart,
} from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

let registered = false

/** 注册 dashboard 所需的图表与组件（SVG renderer 无 canvas 依赖，jsdom 可跑） */
export function registerDashboardCharts(): void {
  if (registered) return
  echarts.use([
    BarChart,
    LineChart,
    PieChart,
    ScatterChart,
    BoxplotChart,
    RadarChart,
    FunnelChart,
    GaugeChart,
    HeatmapChart,
    TreemapChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    RadarComponent,
    VisualMapComponent,
    SVGRenderer,
  ])
  registered = true
}

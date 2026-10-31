/** dashboard 图表数据产物与注册表类型（ADR 0023 P2）.
 *
 * `Dataset` 是「配置 → 数据 → option」的中间层：客户端聚合与服务端聚合
 * 都归一到同一组 kind，`ChartWidget` 只消费 Dataset。
 */

import type { EChartsCoreOption } from 'echarts/core'
import type { Field, RowResponse } from '@/api'
import type { DashboardAggregation, DashboardChart, DashboardChartType, DashboardDisplay } from '../dashboardModel'

export interface CategoryDataset {
  kind: 'category'
  categories: string[]
  series: Array<{ name: string; data: Array<number | null> }>
}

export interface PieDataset {
  kind: 'pie'
  items: Array<{ name: string; value: number }>
}

export interface ScatterDataset {
  kind: 'scatter'
  points: Array<[number, number]>
  rowIds: Array<RowResponse['id']>
}

export interface HistogramDataset {
  kind: 'histogram'
  bins: Array<{ label: string; count: number; from: number; to: number }>
}

export interface BoxplotDataset {
  kind: 'boxplot'
  categories: string[]
  boxes: number[][]
  outliers: Array<[number, number]>
}

export interface RadarDataset {
  kind: 'radar'
  indicators: Array<{ name: string; max: number }>
  series: Array<{ name: string; values: number[] }>
}

export interface FunnelDataset {
  kind: 'funnel'
  items: Array<{ name: string; value: number }>
}

export interface GaugeDataset {
  kind: 'gauge'
  name: string
  value: number | null
  target?: number
}

export interface HeatmapDataset {
  kind: 'heatmap'
  x: string[]
  y: string[]
  /** [xIndex, yIndex, value] */
  values: Array<[number, number, number]>
  max: number
}

export interface TreemapDataset {
  kind: 'treemap'
  nodes: Array<{ name: string; value?: number; children?: Array<{ name: string; value: number }> }>
}

/** 服务端聚合的 KPI（大表不拉行，直接返回单值） */
export interface KpiDataset {
  kind: 'kpi'
  field: string
  agg: DashboardAggregation
  value: number | null
}

/** 服务端返回的明细表（列白名单与行数已按 widget 配置裁剪） */
export interface TableDataset {
  kind: 'table'
  columns: string[]
  rows: RowResponse[]
  total: number
}

/** 取数口径提示（卡壳展示「样本 N / 总行数 M」；服务端路径带缓存标记） */
export interface DatasetMeta {
  scanned: number
  total: number
  truncated: boolean
  cached: boolean
}

type DatasetBase =
  | CategoryDataset
  | PieDataset
  | ScatterDataset
  | HistogramDataset
  | BoxplotDataset
  | RadarDataset
  | FunnelDataset
  | GaugeDataset
  | HeatmapDataset
  | TreemapDataset
  | KpiDataset
  | TableDataset

export type Dataset = DatasetBase & { meta?: DatasetMeta }

/** 主题色（getComputedStyle 读取 CSS 变量；jsdom 回退浅色默认值） */
export interface ThemeColors {
  text: string
  secondary: string
  border: string
  bg: string
}

/** 注册表条目：新增一类图 = 一条 def + 一个 buildOption + 快照测试 */
export interface ChartTypeDef {
  type: DashboardChartType
  label: string
  group: 'comparison' | 'trend' | 'composition' | 'distribution' | 'relation' | 'finance'
  supports: { agg: boolean; multiY: boolean; stack: boolean; dualAxis: boolean; series: boolean }
  minSize: { w: number; h: number }
  buildDataset: (rows: RowResponse[], fields: Field[], cfg: DashboardChart) => Dataset
  buildOption: (data: Dataset, cfg: DashboardChart, theme: ThemeColors, display?: DashboardDisplay) => EChartsCoreOption | null
}

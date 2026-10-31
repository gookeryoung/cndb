/** dashboard 图表 option 装配（ADR 0023 P2）.
 *
 * option 拆成 axis / tooltip / legend / palette 四个 helper，各类型 builder 只写差异；
 * 颜色全部显式注入（主题变量经 ThemeColors 传入），不依赖 ECharts 内建主题。
 */

import type { EChartsCoreOption } from 'echarts/core'
import { olsLine } from '../../chartBoard'
import type { DashboardChart, DashboardDisplay } from '../dashboardModel'
import type {
  BoxplotDataset,
  CategoryDataset,
  Dataset,
  FunnelDataset,
  GaugeDataset,
  HeatmapDataset,
  HistogramDataset,
  PieDataset,
  RadarDataset,
  ScatterDataset,
  ThemeColors,
  TreemapDataset,
} from './types'

export interface Threshold {
  value: number
  color: string
}

/** 默认 8 色板（antd 预设主色，与 ChartView / MatrixView 同口径） */
export const SERIES_COLORS: readonly string[] = [
  '#1677ff', '#52c41a', '#fa8c16', '#722ed1',
  '#13c2c2', '#eb2f96', '#faad14', '#2f54eb',
]

export const PALETTES: Record<string, readonly string[]> = {
  default: SERIES_COLORS,
  warm: ['#fa541c', '#fa8c16', '#faad14', '#d4380d', '#ad4e00', '#ad6800', '#874d00', '#d46b08'],
  cool: ['#1677ff', '#13c2c2', '#2f54eb', '#5b8ff9', '#36cfc9', '#40a9ff', '#597ef7', '#69c0ff'],
}

/** 解析色板名（未知回退默认） */
export function resolvePalette(name?: string): readonly string[] {
  return (name && PALETTES[name]) || SERIES_COLORS
}

export function seriesColor(index: number, palette: readonly string[] = SERIES_COLORS): string {
  return palette[index % palette.length] ?? SERIES_COLORS[0]
}

/** 数值格式化：整数原样，浮点按 decimals / 默认 2 位去尾零；带单位 */
export function makeFormatter(format: DashboardChart['format']): (value: number) => string {
  const decimals = format.decimals
  const unit = format.unit ?? ''
  return (value: number) => {
    if (!Number.isFinite(value)) return '—'
    const body = decimals != null
      ? value.toLocaleString('zh-CN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
      : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    return `${body}${unit}`
  }
}

/** 阈值配色：达到阈值取对应颜色（按 value 升序） */
export function thresholdColor(value: number, thresholds?: Threshold[]): string | undefined {
  if (!thresholds?.length) return undefined
  let hit: string | undefined
  for (const t of thresholds) {
    if (value >= t.value) hit = t.color
  }
  return hit
}

// ── 公共 helper ──────────────────────────────────────

export function categoryAxis(
  theme: ThemeColors,
  data: string[],
  opts: { interval?: number; rotate?: number; name?: string } = {},
): Record<string, unknown> {
  return {
    type: 'category',
    data,
    name: opts.name,
    nameTextStyle: { color: theme.secondary },
    axisLine: { lineStyle: { color: theme.border } },
    axisTick: { lineStyle: { color: theme.border } },
    axisLabel: { color: theme.secondary, interval: opts.interval, rotate: opts.rotate ?? 0 },
  }
}

export function valueAxis(
  theme: ThemeColors,
  opts: { name?: string; formatter?: (v: number) => string; position?: 'left' | 'right' } = {},
): Record<string, unknown> {
  return {
    type: 'value',
    name: opts.name,
    nameTextStyle: { color: theme.secondary },
    scale: true,
    position: opts.position,
    axisLine: { show: false },
    splitLine: { lineStyle: { color: theme.border } },
    axisLabel: { color: theme.secondary, formatter: opts.formatter },
  }
}

export function tooltipStyle(theme: ThemeColors, trigger: 'axis' | 'item'): Record<string, unknown> {
  return {
    trigger,
    backgroundColor: theme.bg,
    borderColor: theme.border,
    textStyle: { color: theme.text },
  }
}

export function legendStyle(
  theme: ThemeColors,
  show = true,
  data?: string[],
): Record<string, unknown> | undefined {
  if (!show) return undefined
  return {
    type: 'scroll',
    top: 0,
    data,
    textStyle: { color: theme.secondary },
    itemGap: 8,
  }
}

/** 绘图区留白：图例占顶部时整体下移 */
function grid(hasLegend: boolean, bottom = 32): Record<string, unknown> {
  return { left: 48, right: 24, top: hasLegend ? 40 : 24, bottom }
}

// ── 各类图 option ────────────────────────────────────

/** bar / line / area / stack / combo：类目 ×（多）度量 */
export function categoryOption(
  data: CategoryDataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  const thresholds = display?.thresholds
  const isLine = cfg.type === 'line' || cfg.type === 'area'
  const stacked = cfg.type === 'stack' || cfg.stack !== 'none'
  const hasLegend = display?.show_legend !== false && (data.series.length > 1)
  const fmt = makeFormatter(cfg.format)
  const multiAxis = cfg.dual_axis && cfg.y.length >= 2
  const series = data.series.map((s, i) => {
    const color = seriesColor(i, palette)
    // 多度量时系列名带「字段 · 系列值」前缀；按前缀归属右轴
    const fieldIndex = cfg.y.findIndex((y) => s.name === y || s.name.startsWith(`${y} · `))
    const yAxisIndex = multiAxis && fieldIndex >= 1 ? 1 : 0
    const items = thresholds?.length
      ? s.data.map((v) => ({
          value: v,
          itemStyle: { color: v != null ? thresholdColor(v, thresholds) ?? color : color },
        }))
      : s.data
    return {
      name: s.name,
      type: isLine ? 'line' : 'bar',
      yAxisIndex: multiAxis ? yAxisIndex : undefined,
      stack: stacked ? 'total' : undefined,
      data: items,
      smooth: cfg.type === 'area',
      areaStyle: cfg.type === 'area' || cfg.stack === 'percent' ? {} : undefined,
      itemStyle: { color },
      lineStyle: isLine ? { color, width: 2 } : undefined,
      emphasis: { focus: 'series' },
    }
  })
  const axis = {
    ...valueAxis(theme, { formatter: fmt }),
    ...(multiAxis ? {} : {}),
  }
  return {
    tooltip: tooltipStyle(theme, 'axis'),
    legend: legendStyle(theme, hasLegend, data.series.map((s) => s.name)),
    grid: grid(hasLegend),
    xAxis: categoryAxis(theme, data.categories, { name: cfg.x }),
    yAxis: multiAxis
      ? [
          valueAxis(theme, { name: cfg.y[0], formatter: fmt }),
          valueAxis(theme, { name: cfg.y[1], formatter: fmt, position: 'right' }),
        ]
      : axis,
    series,
  }
}

export function pieOption(
  data: PieDataset,
  _cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  const showLegend = display?.show_legend !== false
  return {
    tooltip: tooltipStyle(theme, 'item'),
    legend: legendStyle(theme, showLegend),
    series: [
      {
        type: 'pie',
        radius: ['32%', '62%'],
        center: ['50%', '55%'],
        data: data.items.map((it, i) => ({
          name: it.name,
          value: it.value,
          itemStyle: { color: seriesColor(i, palette) },
        })),
        label: { color: theme.secondary },
      },
    ],
  }
}

export function scatterOption(
  data: ScatterDataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  const fmt = makeFormatter(cfg.format)
  const series: Array<Record<string, unknown>> = [
    {
      name: cfg.y[0],
      type: 'scatter',
      data: data.points,
      symbolSize: 9,
      itemStyle: { color: seriesColor(0, palette), opacity: 0.75 },
    },
  ]
  const trend = olsLine(data.points)
  if (trend && data.points.length >= 2) {
    const xs = data.points.map((p) => p[0])
    const xMin = Math.min(...xs)
    const xMax = Math.max(...xs)
    series.push({
      name: '趋势线',
      type: 'line',
      data: [
        [xMin, trend.slope * xMin + trend.intercept],
        [xMax, trend.slope * xMax + trend.intercept],
      ],
      showSymbol: false,
      lineStyle: { color: seriesColor(1, palette), width: 2 },
      silent: true,
      tooltip: { show: false },
    })
  }
  return {
    tooltip: tooltipStyle(theme, 'item'),
    grid: grid(false, 40),
    xAxis: valueAxis(theme, { name: cfg.x, formatter: fmt }),
    yAxis: valueAxis(theme, { name: cfg.y[0], formatter: fmt }),
    series,
  }
}

export function histogramOption(
  data: HistogramDataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  return {
    tooltip: tooltipStyle(theme, 'axis'),
    grid: grid(false, 48),
    xAxis: categoryAxis(theme, data.bins.map((b) => b.label), {
      interval: 0,
      rotate: data.bins.length > 8 ? 40 : 0,
    }),
    yAxis: valueAxis(theme),
    series: [
      {
        name: cfg.y[0],
        type: 'bar',
        data: data.bins.map((b) => b.count),
        barCategoryGap: 0,
        barGap: 0,
        itemStyle: { color: seriesColor(0, palette) },
      },
    ],
  }
}

export function boxplotOption(
  data: BoxplotDataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  return {
    tooltip: tooltipStyle(theme, 'item'),
    grid: grid(false),
    xAxis: categoryAxis(theme, data.categories, { name: cfg.x }),
    yAxis: valueAxis(theme),
    series: [
      {
        name: cfg.y[0],
        type: 'boxplot',
        data: data.boxes,
        itemStyle: { color: `${seriesColor(0, palette)}40`, borderColor: seriesColor(0, palette) },
      },
      {
        name: '离群值',
        type: 'scatter',
        data: data.outliers,
        symbolSize: 8,
        itemStyle: { color: seriesColor(5, palette) },
      },
    ],
  }
}

export function radarOption(
  data: RadarDataset,
  _cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  const showLegend = display?.show_legend !== false && data.series.length > 1
  return {
    tooltip: tooltipStyle(theme, 'item'),
    legend: legendStyle(theme, showLegend, data.series.map((s) => s.name)),
    radar: {
      indicator: data.indicators,
      axisName: { color: theme.secondary },
      splitLine: { lineStyle: { color: theme.border } },
      splitArea: { show: false },
    },
    series: [
      {
        type: 'radar',
        data: data.series.map((s, i) => ({
          name: s.name,
          value: s.values,
          itemStyle: { color: seriesColor(i, palette) },
        })),
      },
    ],
  }
}

export function funnelOption(
  data: FunnelDataset,
  _cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  return {
    tooltip: tooltipStyle(theme, 'item'),
    legend: legendStyle(theme, display?.show_legend !== false),
    series: [
      {
        type: 'funnel',
        left: '10%',
        right: '10%',
        top: 32,
        bottom: 24,
        sort: 'none',
        gap: 2,
        label: { color: theme.text },
        data: data.items.map((it, i) => ({
          name: it.name,
          value: it.value,
          itemStyle: { color: seriesColor(i, palette) },
        })),
      },
    ],
  }
}

export function gaugeOption(
  data: GaugeDataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  const fmt = makeFormatter(cfg.format)
  const value = data.value ?? 0
  const max = data.target && data.target > 0 ? data.target : Math.max(1, Math.ceil(value * 1.2))
  return {
    tooltip: tooltipStyle(theme, 'item'),
    series: [
      {
        type: 'gauge',
        min: 0,
        max,
        progress: { show: true, width: 12 },
        axisLine: { lineStyle: { width: 12, color: [[1, seriesColor(0, palette)]] } },
        axisTick: { show: false },
        splitLine: { length: 10, lineStyle: { color: theme.border } },
        axisLabel: { color: theme.secondary, distance: 18 },
        pointer: { itemStyle: { color: seriesColor(0, palette) } },
        detail: { color: theme.text, formatter: (v: number) => fmt(v) },
        title: { color: theme.secondary },
        data: [{ value, name: cfg.y[0], itemStyle: { color: seriesColor(0, palette) } }],
      },
    ],
  }
}

export function heatmapOption(
  data: HeatmapDataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  const thresholds = display?.thresholds
  const colors = thresholds?.length
    ? thresholds.map((t) => t.color)
    : [seriesColor(0, palette), seriesColor(2, palette), seriesColor(1, palette)]
  return {
    tooltip: {
      ...tooltipStyle(theme, 'item'),
      formatter: (p: { value?: unknown[] }) => {
        const v = p.value ?? []
        return `${data.x[v[0] as number] ?? ''} · ${data.y[v[1] as number] ?? ''}<br/>${v[2]}`
      },
    },
    grid: { left: 72, right: 72, top: 24, bottom: 56 },
    xAxis: categoryAxis(theme, data.x, { name: cfg.x }),
    yAxis: categoryAxis(theme, data.y, { name: cfg.series }),
    visualMap: {
      min: 0,
      max: data.max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 8,
      inRange: { color: colors },
      textStyle: { color: theme.secondary },
    },
    series: [
      {
        name: cfg.y[0],
        type: 'heatmap',
        data: data.values,
        label: { show: false },
        emphasis: { itemStyle: { borderColor: theme.text, borderWidth: 1 } },
      },
    ],
  }
}

export function treemapOption(
  data: TreemapDataset,
  _cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption {
  const palette = resolvePalette(display?.palette)
  return {
    tooltip: tooltipStyle(theme, 'item'),
    series: [
      {
        type: 'treemap',
        left: 8,
        right: 8,
        top: 8,
        bottom: 8,
        leafDepth: 2,
        breadcrumb: { show: false },
        roam: false,
        nodeClick: false,
        label: { color: theme.text },
        upperLabel: { show: true, color: theme.secondary },
        itemStyle: { borderColor: theme.bg, borderWidth: 1 },
        data: data.nodes,
        levels: [
          { itemStyle: { color: seriesColor(0, palette) } },
          { itemStyle: { color: seriesColor(1, palette) } },
        ],
      },
    ],
  }
}

/** 统一入口：按 Dataset kind 装配 option（供 chartRegistry 各类型引用） */
export function buildDatasetOption(
  data: Dataset,
  cfg: DashboardChart,
  theme: ThemeColors,
  display?: DashboardDisplay,
): EChartsCoreOption | null {
  switch (data.kind) {
    case 'category': return categoryOption(data, cfg, theme, display)
    case 'pie': return pieOption(data, cfg, theme, display)
    case 'scatter': return scatterOption(data, cfg, theme, display)
    case 'histogram': return histogramOption(data, cfg, theme, display)
    case 'boxplot': return boxplotOption(data, cfg, theme, display)
    case 'radar': return radarOption(data, cfg, theme, display)
    case 'funnel': return funnelOption(data, cfg, theme, display)
    case 'gauge': return gaugeOption(data, cfg, theme, display)
    case 'heatmap': return heatmapOption(data, cfg, theme, display)
    case 'treemap': return treemapOption(data, cfg, theme, display)
    default: return null
  }
}

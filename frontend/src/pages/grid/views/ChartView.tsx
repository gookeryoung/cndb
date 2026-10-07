/** 图表视图组件 — ECharts adapter + 统计面板.
 *
 * - 6 种图表：bar/line（维度聚合，group_field 多系列）/ pie / scatter（双数值轴 + OLS 趋势线）
 *   / histogram（chartBoard 预计算分箱 + bar 呈现）/ boxplot（五数概括 + IQR 离群点散列）
 * - 纯逻辑全部在 chartBoard.ts（聚合/分箱/统计），本组件只做 ECharts option 装配与生命周期管理
 * - 生命周期：init(SVGRenderer) → setOption(notMerge 覆盖式更新) → ResizeObserver → dispose
 * - 主题桥接：主题切换经 useTheme() 触发重渲染，重新 getComputedStyle 读 var(--cn-*) 注入 option；
 *   系列色用 antd 8 色预设（同 MatrixView AXIS_COLORS 策略，数据分类着色不绑主题变量）
 * - scatter 点击散点打开行详情（rowIds 与 points 平行，经 ref 持最新值避免闭包过期）
 * - StatsPanel：描述统计（样本标准差 n-1 / 线性插值分位 / IQR 离群值）+ 样本量/总行数，
 *   暴露 fetch-all 截断口径；散点图附加 Pearson r / R² / 回归系数
 */

import { useEffect, useMemo, useRef } from 'react'
import { Empty, Tooltip } from 'antd'
import * as echarts from 'echarts/core'
import { BarChart, BoxplotChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import type { RowResponse, Field, View } from '@/api'
import { useTheme } from '@/theme/ThemeProvider'
import { resolveOpts, CHART_OPTIONS } from '../view-config/viewOptionSchema'
import {
  buildChartData,
  computeStats,
  extractNumbers,
  olsLine,
  type ChartConfig,
  type ChartData,
  type StatsResult,
} from './chartBoard'

// 按需注册（tree-shaking 控体积；SVGRenderer 无 canvas 依赖，jsdom 可跑）
echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, BoxplotChart,
  GridComponent, TooltipComponent, LegendComponent, SVGRenderer,
])

/** 系列色板 —— antd v5 官方预设主色，按索引循环（同 MatrixView AXIS_COLORS / tagColors 策略） */
const SERIES_COLORS: readonly string[] = [
  '#1677ff', // blue
  '#52c41a', // green
  '#fa8c16', // orange
  '#722ed1', // purple
  '#13c2c2', // cyan
  '#eb2f96', // magenta
  '#faad14', // gold
  '#2f54eb', // geekblue
]

const seriesColor = (index: number): string => SERIES_COLORS[index % SERIES_COLORS.length]

// ── 主题色桥接 ────────────────────────────────────────

/** 主题相关颜色（getComputedStyle 读 CSS 变量；jsdom/SSR 环境回退浅色默认值） */
interface ThemeColors {
  text: string
  secondary: string
  border: string
  bg: string
}

function readThemeColors(): ThemeColors {
  const read = (name: string, fallback: string): string => {
    if (typeof document === 'undefined') return fallback
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  }
  return {
    text: read('--cn-text-primary', '#1f2937'),
    secondary: read('--cn-text-secondary', '#6b7280'),
    border: read('--cn-border', '#e5e7eb'),
    bg: read('--cn-bg-container', '#ffffff'),
  }
}

// ── ECharts option 装配 ───────────────────────────────

/** 类目轴公共样式 */
function categoryAxis(colors: ThemeColors, data: string[]): Record<string, unknown> {
  return {
    type: 'category',
    data,
    axisLine: { lineStyle: { color: colors.border } },
    axisTick: { lineStyle: { color: colors.border } },
    axisLabel: { color: colors.secondary },
  }
}

/** 数值轴公共样式（scale: true 不强制从 0 起） */
function valueAxis(colors: ThemeColors): Record<string, unknown> {
  return {
    type: 'value',
    scale: true,
    axisLine: { show: false },
    splitLine: { lineStyle: { color: colors.border } },
    axisLabel: { color: colors.secondary },
  }
}

/** tooltip / legend 公共样式 */
function tooltipStyle(colors: ThemeColors): Record<string, unknown> {
  return {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    textStyle: { color: colors.text },
  }
}

/** 散点 OLS 趋势线系列（两端点画线；X 恒定奇异时返回 null） */
function trendLineSeries(points: Array<[number, number]>, color: string): Record<string, unknown> | null {
  const ols = olsLine(points)
  if (!ols) return null
  const xs = points.map((p) => p[0])
  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  return {
    name: '趋势线',
    type: 'line',
    data: [
      [xMin, ols.slope * xMin + ols.intercept],
      [xMax, ols.slope * xMax + ols.intercept],
    ],
    showSymbol: false,
    lineStyle: { color, width: 2 },
    itemStyle: { color },
    silent: true,
    tooltip: { show: false },
  }
}

/** 按图表数据装配 ECharts option（纯函数，颜色全部显式注入不依赖 ECharts 内建主题） */
function buildOption(data: ChartData, cfg: ChartConfig, colors: ThemeColors): EChartsCoreOption {
  switch (data.kind) {
    case 'category': {
      const isLine = cfg.chart_type === 'line'
      const series = data.series.map((s, i) => ({
        name: s.name,
        type: isLine ? 'line' : 'bar',
        data: s.data,
        itemStyle: { color: seriesColor(i) },
        lineStyle: isLine ? { color: seriesColor(i), width: 2 } : undefined,
        emphasis: { focus: 'series' },
      }))
      return {
        tooltip: { trigger: 'axis', ...tooltipStyle(colors) },
        legend: data.series.length > 1 ? { textStyle: { color: colors.secondary } } : undefined,
        grid: { left: 48, right: 24, top: data.series.length > 1 ? 40 : 24, bottom: 32 },
        xAxis: categoryAxis(colors, data.categories),
        yAxis: valueAxis(colors),
        series,
      }
    }
    case 'pie':
      return {
        tooltip: { trigger: 'item', ...tooltipStyle(colors) },
        legend: { textStyle: { color: colors.secondary } },
        series: [{
          type: 'pie',
          radius: '62%',
          center: ['50%', '52%'],
          data: data.items.map((it, i) => ({
            name: it.name,
            value: it.value,
            itemStyle: { color: seriesColor(i) },
          })),
          label: { color: colors.secondary },
        }],
      }
    case 'scatter': {
      const series: Array<Record<string, unknown>> = [{
        name: '散点',
        type: 'scatter',
        data: data.points,
        symbolSize: 9,
        itemStyle: { color: seriesColor(0), opacity: 0.75 },
      }]
      if (cfg.show_trend_line) {
        const trend = trendLineSeries(data.points, seriesColor(1))
        if (trend) series.push(trend)
      }
      return {
        tooltip: { trigger: 'item', ...tooltipStyle(colors) },
        grid: { left: 56, right: 32, top: 24, bottom: 40 },
        xAxis: { ...valueAxis(colors), name: cfg.x_field ?? 'X', nameTextStyle: { color: colors.secondary } },
        yAxis: { ...valueAxis(colors), name: cfg.y_field ?? 'Y', nameTextStyle: { color: colors.secondary } },
        series,
      }
    }
    case 'histogram':
      return {
        tooltip: { trigger: 'axis', ...tooltipStyle(colors) },
        grid: { left: 56, right: 24, top: 24, bottom: 48 },
        xAxis: {
          ...categoryAxis(colors, data.bins.map((b) => b.label)),
          axisLabel: { color: colors.secondary, interval: 0, rotate: data.bins.length > 8 ? 40 : 0 },
        },
        yAxis: valueAxis(colors),
        series: [{
          name: cfg.measure_field ?? '频数',
          type: 'bar',
          data: data.bins.map((b) => b.count),
          // 直方图语义：柱紧贴无缝隙
          barCategoryGap: 0,
          barGap: 0,
          itemStyle: { color: seriesColor(0) },
        }],
      }
    case 'boxplot':
      return {
        tooltip: { trigger: 'item', ...tooltipStyle(colors) },
        grid: { left: 56, right: 24, top: 24, bottom: 32 },
        xAxis: categoryAxis(colors, data.categories),
        yAxis: valueAxis(colors),
        series: [
          {
            name: cfg.measure_field ?? '',
            type: 'boxplot',
            data: data.boxes,
            itemStyle: { color: '#5b8ff940', borderColor: seriesColor(0) },
          },
          {
            name: '离群值',
            type: 'scatter',
            data: data.outliers,
            symbolSize: 8,
            itemStyle: { color: seriesColor(5) },
          },
        ],
      }
  }
}

// ── 统计面板 ──────────────────────────────────────────

/** 统计值显示：null 显示 —；整数原样，浮点保留 6 位有效数字去尾零 */
function fmtStat(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  if (Number.isInteger(v)) return String(v)
  return String(parseFloat(v.toPrecision(6)))
}

/** 散点相关与回归摘要 */
interface ScatterSummary {
  r: number | null
  r2: number | null
  slope: number | null
  intercept: number | null
}

/** 描述统计面板（统计口径 tooltip + 样本量/总行数截断提示） */
function StatsPanel({
  stats,
  total,
  fieldName,
  scatter,
}: {
  stats: StatsResult
  /** 服务端总行数；undefined 时只显示样本量 */
  total?: number
  /** 被统计的字段名（散点为 Y 字段） */
  fieldName: string
  /** 散点图附加的相关与回归摘要；非散点传 undefined */
  scatter?: ScatterSummary
}) {
  const items: Array<[string, string]> = [
    ['计数', fmtStat(stats.count)],
    ['求和', fmtStat(stats.sum)],
    ['均值', fmtStat(stats.mean)],
    ['中位数', fmtStat(stats.median)],
    ['众数', fmtStat(stats.mode)],
    ['样本标准差', fmtStat(stats.std)],
    ['最小值', fmtStat(stats.min)],
    ['最大值', fmtStat(stats.max)],
    ['极差', fmtStat(stats.range)],
    ['P25', fmtStat(stats.p25)],
    ['P75', fmtStat(stats.p75)],
    ['IQR', fmtStat(stats.iqr)],
    ['偏度', fmtStat(stats.skewness)],
    ['离群值数', fmtStat(stats.outlierCount)],
  ]
  return (
    <div
      data-testid="chart-stats-panel"
      style={{
        border: '1px solid var(--cn-border)', borderRadius: 8,
        background: 'var(--cn-bg-container)', padding: '10px 14px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--cn-text-primary)' }}>
          描述统计（{fieldName}）
        </span>
        <Tooltip
          title={
            <div style={{ lineHeight: 1.8 }}>
              样本标准差采用 n-1 口径；分位数采用线性插值（R-7）；
              离群值为 IQR 法（Q1-1.5·IQR ~ Q3+1.5·IQR 之外）；
              空值与非数值行已剔除
            </div>
          }
        >
          <span
            data-testid="chart-stats-scope"
            style={{ fontSize: 12, color: 'var(--cn-text-secondary)', cursor: 'help' }}
          >
            样本量 {stats.count}{total !== undefined ? ` / 总行数 ${total}` : ''}
          </span>
        </Tooltip>
      </div>
      <div
        style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
          gap: '4px 16px', fontSize: 12,
        }}
      >
        {items.map(([label, value]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ color: 'var(--cn-text-secondary)' }}>{label}</span>
            <span style={{ color: 'var(--cn-text-primary)', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
          </div>
        ))}
        {scatter && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--cn-text-secondary)' }}>Pearson r</span>
              <span style={{ color: 'var(--cn-text-primary)', fontVariantNumeric: 'tabular-nums' }}>{fmtStat(scatter.r)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--cn-text-secondary)' }}>R²</span>
              <span style={{ color: 'var(--cn-text-primary)', fontVariantNumeric: 'tabular-nums' }}>{fmtStat(scatter.r2)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--cn-text-secondary)' }}>回归斜率</span>
              <span style={{ color: 'var(--cn-text-primary)', fontVariantNumeric: 'tabular-nums' }}>{fmtStat(scatter.slope)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--cn-text-secondary)' }}>回归截距</span>
              <span style={{ color: 'var(--cn-text-primary)', fontVariantNumeric: 'tabular-nums' }}>{fmtStat(scatter.intercept)}</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────

interface ChartViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  /** 服务端总行数（StatsPanel 显示「样本量 N / 总行数 M」暴露 fetch-all 截断口径） */
  total?: number
  onRowClick?: (r: RowResponse) => void
}

/** 检查 chart_type 对应的必填字段是否已配置且存在；返回缺失项的中文标签列表 */
function missingFieldLabels(cfg: ChartConfig, fields: Field[]): string[] {
  const has = (name?: string) => !!name && fields.some((f) => f.name === name)
  const out: string[] = []
  if (cfg.chart_type === 'scatter') {
    if (!has(cfg.x_field)) out.push('X 数值字段')
    if (!has(cfg.y_field)) out.push('Y 数值字段')
  } else if (cfg.chart_type === 'histogram') {
    if (!has(cfg.measure_field)) out.push('度量字段')
  } else {
    if (!has(cfg.dimension_field)) out.push('维度字段')
    if (!has(cfg.measure_field)) out.push('度量字段')
  }
  return out
}

export default function ChartView({ rows, fields, view, total, onRowClick }: ChartViewProps) {
  // 订阅主题：主题切换触发重渲染 → 重新读 CSS 变量重建 option（ThemeProvider 主题 state 驱动联动）
  const { mode: themeMode } = useTheme()

  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, CHART_OPTIONS),
    [view?.view_options],
  )
  const cfg = opts as unknown as ChartConfig

  const missing = useMemo(() => missingFieldLabels(cfg, fields), [cfg, fields])
  const hasChart = missing.length === 0

  const data = useMemo(
    () => (hasChart ? buildChartData(rows, fields, cfg) : null),
    [hasChart, rows, fields, cfg],
  )

  const option = useMemo(
    () => (data ? buildOption(data, cfg, readThemeColors()) : null),
    // themeMode 进依赖：主题切换时 getComputedStyle 结果已更新，需重建 option
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, cfg, themeMode],
  )

  // scatter 点击行详情：经 ref 持最新 rows/rowIds/回调，避免 init effect 闭包过期
  const clickCtxRef = useRef<{ rows: RowResponse[]; rowIds: Array<RowResponse['id']> }>({ rows: [], rowIds: [] })
  clickCtxRef.current = {
    rows,
    rowIds: data?.kind === 'scatter' ? data.rowIds : [],
  }
  const onRowClickRef = useRef(onRowClick)
  onRowClickRef.current = onRowClick

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)

  // init / dispose + ResizeObserver：仅 hasChart 时挂容器；chart_type 切换不重建（setOption 覆盖）
  useEffect(() => {
    if (!hasChart || !containerRef.current) return
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    chart.on('click', (params) => {
      if (params.seriesType !== 'scatter') return
      const ctx = clickCtxRef.current
      const rowId = ctx.rowIds[params.dataIndex]
      const row = ctx.rows.find((r) => r.id === rowId)
      if (row) onRowClickRef.current?.(row)
    })
    const ro = new ResizeObserver(() => { chartRef.current?.resize() })
    ro.observe(containerRef.current)
    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [hasChart])

  // setOption（notMerge：图表类型/系列数变化时彻底替换，防旧系列残留）
  useEffect(() => {
    if (!chartRef.current || !option) return
    chartRef.current.setOption(option, true)
  }, [option])

  // 统计面板数据：度量字段原始值（散点取 Y 字段 + 相关回归摘要）
  const statsField = cfg.chart_type === 'scatter' ? cfg.y_field : cfg.measure_field
  const stats = useMemo(
    () => computeStats(extractNumbers(rows, statsField)),
    [rows, statsField],
  )
  const scatterSummary = useMemo<ScatterSummary | undefined>(
    () => {
      if (cfg.chart_type !== 'scatter' || !data || data.kind !== 'scatter' || data.points.length < 2) return undefined
      const ols = olsLine(data.points)
      return ols
        ? { r: ols.r, r2: ols.r2, slope: ols.slope, intercept: ols.intercept }
        : undefined
    },
    [cfg.chart_type, data],
  )

  // 未配必填字段 → 引导空态（后端校验挡新视图，这里兜底历史数据/清空场景）
  if (!hasChart) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description={`图表视图需配置${missing.join('与')}（视图设置）`} data-testid="chart-empty-config" />
      </div>
    )
  }

  // 无数据 → 引导空态（与矩阵/看板语义一致）
  if (!rows.length) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="这张表还没有数据，新增行后即可生成图表" data-testid="chart-empty-rows" />
      </div>
    )
  }

  return (
    <div
      style={{
        flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12,
        padding: '12px 16px', overflow: 'auto', background: 'var(--cn-bg-container)',
        border: '1px solid var(--cn-border)', borderRadius: 8,
      }}
    >
      <div ref={containerRef} data-testid="chart-container" style={{ flex: 1, minHeight: 320 }} />
      {cfg.show_stats_panel !== false && stats && statsField && (
        <StatsPanel stats={stats} total={total} fieldName={statsField} scatter={scatterSummary} />
      )}
    </div>
  )
}

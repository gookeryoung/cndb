/** K 线视图 — 左侧标的列表 + 右侧行内 K 线图表.
 *
 * - 数据全部来自行内 JSON（日线三复权 + 周/月前复权），经 klineBoard 解析/派生；
 *   切周期与复权只换序列，不重新取数（周/月后复权与不复权由日线同口径派生）。
 * - 左侧列表：搜索、代码/名称/最新价/涨跌幅/成交量、选中高亮；原生 button 自带 Enter/Space 键盘选中。
 * - 工具栏：周期（日/周/月）、复权（前/后/不复权，缺少对应字段的选项禁用）、均线/成交量开关。
 * - ECharts 按需注册：CandlestickChart / LineChart / BarChart / Grid / Tooltip / Legend /
 *   DataZoom / AxisPointer / SVGRenderer（DataZoom 同时作用于价格与成交量两个 grid）。
 * - 生命周期与 ChartView 一致：init(SVGRenderer) → setOption(notMerge) → ResizeObserver → dispose；
 *   图表容器常挂载、空态/错误态用兄弟覆盖层，避免 ECharts dispose 与 React removeChild 冲突。
 * - 主题切换经 useTheme 触发重渲染重建 option；红涨绿跌为固定色（不随主题变）。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Empty, Input, Segmented, Select, Switch, Tooltip } from 'antd'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent,
} from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import type { Field, ID, RowResponse, View } from '@/api'
import { useTheme } from '@/theme/ThemeProvider'
import { useResponsive } from '@/hooks/useResponsive'
import { toNumber } from './chartBoard'
import { KLINE_OPTIONS, resolveOpts } from '../view-config/viewOptionSchema'
import {
  ADJUST_LABELS,
  PERIOD_LABELS,
  buildKlineOption,
  compactNumber,
  formatPct,
  formatPrice,
  latestQuote,
  parseMaPeriods,
  quoteColor,
  resolveSeries,
  type KlineAdjust,
  type KlineConfig,
  type KlineOptionTheme,
  type KlinePeriod,
} from './klineBoard'

// 按需注册（tree-shaking 控体积；SVGRenderer 无 canvas 依赖，jsdom 可跑）
echarts.use([
  CandlestickChart, LineChart, BarChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, AxisPointerComponent,
  SVGRenderer,
])

// ── 主题色桥接 ────────────────────────────────────────

/** 读主题 CSS 变量（jsdom/SSR 环境回退浅色默认值） */
function readThemeColors(): KlineOptionTheme {
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

// ── 行级展示辅助 ──────────────────────────────────────

/** 列表项标题：代码 + 名称，均缺失时回退行 id */
function rowLabel(row: RowResponse, cfg: KlineConfig): string {
  const symbol = cfg.symbol_field ? String(row[cfg.symbol_field] ?? '').trim() : ''
  const name = cfg.name_field ? String(row[cfg.name_field] ?? '').trim() : ''
  return [symbol, name].filter(Boolean).join(' ') || `行 #${row.id}`
}

/** 行级最新价/涨跌幅/量额（取字段值为准） */
function rowQuote(row: RowResponse, cfg: KlineConfig) {
  return {
    price: cfg.price_field ? toNumber(row[cfg.price_field]) : null,
    pct: cfg.change_pct_field ? toNumber(row[cfg.change_pct_field]) : null,
    volume: cfg.volume_field ? toNumber(row[cfg.volume_field]) : null,
    amount: cfg.amount_field ? toNumber(row[cfg.amount_field]) : null,
    date: cfg.date_field && row[cfg.date_field] ? String(row[cfg.date_field]) : null,
  }
}

/** 周期/复权分段控件选项（顺序即展示顺序） */
const PERIOD_OPTIONS = (Object.keys(PERIOD_LABELS) as KlinePeriod[]).map((p) => ({
  value: p,
  label: PERIOD_LABELS[p],
}))
const ADJUST_OPTIONS = (Object.keys(ADJUST_LABELS) as KlineAdjust[]).map((a) => ({
  value: a,
  label: ADJUST_LABELS[a],
}))

/** 序列字段键清单（配置校验与派生能力判断共用） */
const SERIES_KEYS = [
  'day_qfq_field', 'day_hfq_field', 'day_none_field', 'week_qfq_field', 'month_qfq_field',
] as const

// ── 组件 ──────────────────────────────────────────────

interface KlineViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  /** 服务端总行数（列表头展示截断口径） */
  total?: number
  /** 外部选中行（表格选择/底部操作）→ 视图内选中 */
  initialSelectedRowId?: ID | null
  /** 视图内选中行 → 回写表格选择 */
  onSelectRow?: (id: ID) => void
}

export default function KlineView({
  rows, fields, view, total, initialSelectedRowId, onSelectRow,
}: KlineViewProps) {
  const { mode: themeMode } = useTheme()
  const { isMobile } = useResponsive()

  const rawOpts = view?.view_options as Record<string, unknown> | undefined
  const cfg = useMemo(
    () => resolveOpts(rawOpts, KLINE_OPTIONS) as unknown as KlineConfig,
    [rawOpts],
  )

  const [period, setPeriod] = useState<KlinePeriod>(cfg.default_period ?? 'day')
  const [adjust, setAdjust] = useState<KlineAdjust>(cfg.default_adjust ?? 'qfq')
  const [showMa, setShowMa] = useState(cfg.show_ma !== false)
  const [showVolume, setShowVolume] = useState(cfg.show_volume !== false)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<ID | null>(initialSelectedRowId ?? null)

  // 切换视图 → 周期/复权/开关回到该视图的默认配置
  useEffect(() => {
    setPeriod(cfg.default_period ?? 'day')
    setAdjust(cfg.default_adjust ?? 'qfq')
    setShowMa(cfg.show_ma !== false)
    setShowVolume(cfg.show_volume !== false)
  }, [view?.id, cfg.default_period, cfg.default_adjust, cfg.show_ma, cfg.show_volume])

  // 外部选中行 → 内部（仅当该行存在时采纳）
  useEffect(() => {
    if (initialSelectedRowId == null) return
    if (!rows.some((r) => r.id === initialSelectedRowId)) return
    setSelectedId((prev) => (prev === initialSelectedRowId ? prev : initialSelectedRowId))
  }, [initialSelectedRowId, rows])

  const configMissing = useMemo(() => {
    const out: string[] = []
    if (!cfg.symbol_field || !fields.some((f) => f.name === cfg.symbol_field)) out.push('标的字段')
    const hasSeries = SERIES_KEYS.some((k) => cfg[k] && fields.some((f) => f.name === cfg[k]))
    if (!hasSeries) out.push('K 线序列字段')
    return out
  }, [cfg, fields])

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => {
      const symbol = cfg.symbol_field ? String(r[cfg.symbol_field] ?? '') : ''
      const name = cfg.name_field ? String(r[cfg.name_field] ?? '') : ''
      return symbol.toLowerCase().includes(q) || name.toLowerCase().includes(q)
    })
  }, [rows, query, cfg.symbol_field, cfg.name_field])

  const selectedRow = useMemo(() => {
    const hit = selectedId != null ? rows.find((r) => r.id === selectedId) : undefined
    if (hit) return hit
    // 未显式选中 → 优先落在首只有当前周期/复权序列的行，避免打开即空态
    // （只探前 50 行：全市场大列表下不必解析全部 JSON）
    const preferred = rows
      .slice(0, 50)
      .find((r) => resolveSeries(r, cfg, period, adjust).points.length > 0)
    return preferred ?? rows[0] ?? null
  }, [rows, selectedId, cfg, period, adjust])

  const series = useMemo(
    () => (selectedRow ? resolveSeries(selectedRow, cfg, period, adjust) : null),
    [selectedRow, cfg, period, adjust],
  )

  // 当前周期下各复权口径是否可用（决定 Segmented 选项禁用）
  const adjustAvailable = useMemo<Record<KlineAdjust, boolean>>(() => {
    const dayQfq = !!cfg.day_qfq_field
    const dayHfq = !!cfg.day_hfq_field
    const dayNone = !!cfg.day_none_field
    if (period === 'day') {
      return { qfq: dayQfq, hfq: dayHfq, none: dayNone }
    }
    return {
      qfq: !!cfg.week_qfq_field || dayQfq || !!cfg.month_qfq_field,
      hfq: dayHfq,
      none: dayNone,
    }
  }, [period, cfg])

  // 切周期后若当前复权口径不可用 → 回退前复权（前复权也不可用时保留，交给空态提示）
  useEffect(() => {
    if (adjustAvailable[adjust]) return
    if (adjustAvailable.qfq) setAdjust('qfq')
  }, [adjustAvailable, adjust])

  const quote = useMemo(() => {
    const base = selectedRow ? rowQuote(selectedRow, cfg) : null
    const last = series ? latestQuote(series.points) : null
    return {
      price: base?.price ?? last?.close ?? null,
      pct: base?.pct ?? last?.pct_change ?? null,
      volume: base?.volume ?? last?.volume ?? null,
      amount: base?.amount ?? last?.amount ?? null,
      date: base?.date ?? last?.date ?? null,
    }
  }, [selectedRow, series, cfg])

  const handleSelect = (id: ID) => {
    setSelectedId(id)
    onSelectRow?.(id)
  }

  // ── ECharts 生命周期 ──
  const chartAreaReady = rows.length > 0 && configMissing.length === 0
  const hasChart = !!series && series.points.length > 0

  const option = useMemo(() => {
    if (!series || !series.points.length) return null
    return buildKlineOption(series.points, {
      showMa,
      showVolume,
      maPeriods: parseMaPeriods(cfg.ma_periods),
      theme: readThemeColors(),
    })
    // themeMode 进依赖：主题切换时 getComputedStyle 结果已更新，需重建 option
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, showMa, showVolume, cfg.ma_periods, themeMode])

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)

  useEffect(() => {
    if (!chartAreaReady || !containerRef.current) return
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    const ro = new ResizeObserver(() => { chartRef.current?.resize() })
    ro.observe(containerRef.current)
    return () => {
      ro.disconnect()
      try {
        chart.dispose()
      } catch {
        // 容器可能已被宿主整体卸载/清空（ECharts dispose 内部会 removeChild），不应阻断卸载流程
      }
      chartRef.current = null
    }
  }, [chartAreaReady])

  useEffect(() => {
    if (!chartRef.current || !option) return
    chartRef.current.setOption(option as EChartsCoreOption, true)
  }, [option])

  // ── 空态 ──
  if (!rows.length) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="这张表还没有数据，新增行并同步 K 线后即可查看" data-testid="kline-empty-rows" />
      </div>
    )
  }
  if (configMissing.length) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty
          description={`K 线视图需配置${configMissing.join('与')}（视图设置）`}
          data-testid="kline-empty-config"
        />
      </div>
    )
  }

  const title = selectedRow ? rowLabel(selectedRow, cfg) : '未选中标的'
  const adjustOptions = ADJUST_OPTIONS.map((o) => ({ ...o, disabled: !adjustAvailable[o.value] }))
  const seriesMeta = series && series.points.length
    ? `共 ${series.points.length} 根 · ${PERIOD_LABELS[period]}${ADJUST_LABELS[adjust]}` +
      (series.source === 'derived' ? `（由「${series.field}」派生）` : `（${series.field}）`)
    : ''

  const emptyState = !selectedRow
    ? { description: '没有匹配的标的，请调整搜索词', error: '' }
    : series && series.points.length === 0
      ? { description: series.message ?? '暂无 K 线数据', error: series.error ?? '' }
      : null

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 12 }}>
      {/* 左侧标的列表（窄屏隐藏，改顶部下拉） */}
      <aside
        data-testid="kline-stock-list"
        style={{
          width: 280, minWidth: 240, minHeight: 0,
          display: isMobile ? 'none' : 'flex', flexDirection: 'column', gap: 8,
          background: 'var(--cn-bg-container)', border: '1px solid var(--cn-border)',
          borderRadius: 8, padding: '10px 10px',
        }}
      >
        <Input
          size="small"
          allowClear
          placeholder="搜索代码 / 名称"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div data-testid="kline-stock-count" style={{ fontSize: 11, color: 'var(--cn-text-secondary)' }}>
          共 {rows.length} 只{total !== undefined && total !== rows.length ? `（服务端 ${total}）` : ''}
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {filteredRows.map((r) => {
            const q = rowQuote(r, cfg)
            const selected = selectedRow?.id === r.id
            return (
              <button
                key={r.id}
                type="button"
                data-testid={`kline-stock-${r.id}`}
                data-selected={selected ? 'true' : 'false'}
                aria-pressed={selected}
                onClick={() => handleSelect(r.id)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 1,
                  width: '100%', padding: '5px 8px', textAlign: 'left',
                  border: 'none', borderRadius: 6, cursor: 'pointer',
                  background: selected ? 'rgba(22,119,255,0.12)' : 'transparent',
                  boxShadow: selected ? 'inset 0 0 0 1px var(--cn-primary, #1677ff)' : 'none',
                }}
              >
                <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 12, color: 'var(--cn-text-primary)' }}>
                    {cfg.symbol_field ? String(r[cfg.symbol_field] ?? '') || `#${r.id}` : `#${r.id}`}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--cn-text-primary)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatPrice(q.price)}
                  </span>
                </span>
                <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span
                    style={{
                      fontSize: 11, color: 'var(--cn-text-secondary)', minWidth: 0,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}
                  >
                    {cfg.name_field ? String(r[cfg.name_field] ?? '') || '—' : '—'}
                  </span>
                  <span style={{ fontSize: 11, color: quoteColor(q.pct), fontVariantNumeric: 'tabular-nums' }}>
                    {formatPct(q.pct)}
                  </span>
                </span>
                <span style={{ fontSize: 10, color: 'var(--cn-text-secondary)' }}>
                  量 {compactNumber(q.volume)}
                </span>
              </button>
            )
          })}
          {filteredRows.length === 0 && (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的标的" />
          )}
        </div>
      </aside>

      {/* 右侧图表区 */}
      <section
        style={{
          flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8,
          background: 'var(--cn-bg-container)', border: '1px solid var(--cn-border)',
          borderRadius: 8, padding: '10px 12px',
        }}
      >
        {/* 窄屏标的切换（恒占位，保持子节点索引稳定避免图表容器重挂载） */}
        <div style={{ display: isMobile ? 'block' : 'none' }}>
          <Select
            size="small"
            showSearch
            style={{ width: '100%', marginBottom: 8 }}
            placeholder="选择标的"
            value={selectedRow?.id}
            onChange={(v) => handleSelect(v)}
            optionFilterProp="label"
            options={filteredRows.map((r) => {
              const q = rowQuote(r, cfg)
              return { value: r.id, label: `${rowLabel(r, cfg)} ${formatPct(q.pct)}` }
            })}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ minWidth: 160 }}>
            <div
              data-testid="kline-title"
              style={{ fontWeight: 600, fontSize: 14, color: 'var(--cn-text-primary)' }}
            >
              {title}
            </div>
            <div style={{ fontSize: 12, color: 'var(--cn-text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
              <span data-testid="kline-latest-price" style={{ marginRight: 8 }}>
                最新价 {formatPrice(quote.price)}
              </span>
              <span data-testid="kline-change-pct" style={{ color: quoteColor(quote.pct) }}>
                {formatPct(quote.pct)}
              </span>
              {quote.date && <span style={{ marginLeft: 8 }}>{quote.date}</span>}
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <Segmented
              size="small"
              data-testid="kline-period"
              value={period}
              onChange={(v) => setPeriod(v as KlinePeriod)}
              options={PERIOD_OPTIONS}
            />
            <Segmented
              size="small"
              data-testid="kline-adjust"
              value={adjust}
              onChange={(v) => setAdjust(v as KlineAdjust)}
              options={adjustOptions}
            />
            <Tooltip title="叠加 MA 均线（周期见视图设置）">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--cn-text-secondary)' }}>
                <Switch size="small" checked={showMa} onChange={setShowMa} data-testid="kline-toggle-ma" />
                均线
              </span>
            </Tooltip>
            <Tooltip title="价格下方显示成交量副图">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--cn-text-secondary)' }}>
                <Switch size="small" checked={showVolume} onChange={setShowVolume} data-testid="kline-toggle-volume" />
                成交量
              </span>
            </Tooltip>
          </div>
        </div>

        {/* 图表容器常挂载（ECharts dispose 会清空容器，空态用兄弟覆盖层而非替换子树） */}
        <div style={{ flex: 1, minHeight: 320, position: 'relative', display: 'flex' }}>
          <div
            ref={containerRef}
            data-testid="kline-chart-container"
            data-chart-ready={hasChart ? 'true' : 'false'}
            style={{
              flex: 1, minWidth: 0,
              visibility: hasChart ? 'visible' : 'hidden',
              pointerEvents: hasChart ? 'auto' : 'none',
            }}
          />
          {emptyState && (
            <div
              style={{
                position: 'absolute', inset: 0, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
              }}
            >
              <Empty
                data-testid={emptyState.error ? 'kline-error' : 'kline-empty-series'}
                description={
                  <div style={{ maxWidth: 460, textAlign: 'center' }}>
                    <div>{emptyState.description}</div>
                    {emptyState.error && (
                      <div style={{ fontSize: 12, color: 'var(--cn-text-secondary)', marginTop: 4 }}>
                        {emptyState.error}
                      </div>
                    )}
                  </div>
                }
              />
            </div>
          )}
        </div>

        {seriesMeta && (
          <div data-testid="kline-source" style={{ fontSize: 11, color: 'var(--cn-text-secondary)' }}>
            {seriesMeta}
          </div>
        )}
      </section>
    </div>
  )
}

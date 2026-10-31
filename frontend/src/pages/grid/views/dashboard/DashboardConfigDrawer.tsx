/** dashboard 属性面板（ADR 0023 P1）.
 *
 * 三段：布局（坐标 / 预设 / 增删）· 数据（按 widget 类型分派）· 外观（标题 / 画布参数）。
 * 面板只读 draft 并回调 updater，所有变更仍由 DashboardView 的草稿栈承接。
 */

import { useState } from 'react'
import { Button, Divider, Drawer, Empty, Input, InputNumber, Select, Space, Switch, Tabs, Typography } from 'antd'
import type { Field } from '@/api'
import {
  DASHBOARD_TYPE_LABELS,
  type DashboardChartSort,
  type DashboardConfig,
  type DashboardThreshold,
  type DashboardWidget,
  type DashboardWidgetType,
} from './dashboardModel'
import { CHART_GROUP_LABELS, CHART_TYPE_DEFS, getChartTypeDef } from './chart/chartRegistry'
import { PALETTES } from './chart/option'
import {
  DASHBOARD_COLS,
  DASHBOARD_MAX_H,
  DASHBOARD_PRESETS,
  type LayoutPresetKey,
  type WidgetBox,
} from './dashboardLayout'

const NUMERIC_TYPES = new Set(['number', 'float', 'percentage', 'timestamp'])
const DATE_TYPES = new Set(['date', 'datetime'])

/** 图表类型按注册表分组（新增一类图自动出现在面板） */
const CHART_TYPE_OPTIONS = Object.entries(CHART_GROUP_LABELS).map(([group, label]) => ({
  label,
  options: CHART_TYPE_DEFS
    .filter((def) => def.group === group)
    .map((def) => ({ value: def.type, label: def.label })),
}))

const AGG_OPTIONS = [
  { value: 'sum', label: '求和' },
  { value: 'avg', label: '平均' },
  { value: 'count', label: '计数' },
  { value: 'min', label: '最小' },
  { value: 'max', label: '最大' },
  { value: 'median', label: '中位数' },
]

const SORT_OPTIONS: Array<{ value: DashboardChartSort; label: string }> = [
  { value: 'none', label: '不排序' },
  { value: 'x_asc', label: '维度升序' },
  { value: 'x_desc', label: '维度降序' },
  { value: 'y_asc', label: '数值升序' },
  { value: 'y_desc', label: '数值降序' },
]

/** 支持排序 / TopN 的图表类型（类目轴类） */
const SORTABLE_TYPES = new Set(['bar', 'line', 'area', 'stack', 'combo', 'pie', 'funnel', 'radar', 'heatmap', 'treemap'])

const THRESHOLD_COLORS = ['#52c41a', '#faad14', '#fa541c', '#cf1322', '#1677ff']

const GRANULARITY_OPTIONS = [
  { value: 'day', label: '按日' },
  { value: 'week', label: '按周' },
  { value: 'month', label: '按月' },
  { value: 'quarter', label: '按季' },
  { value: 'year', label: '按年' },
]

const isNumeric = (f: Field): boolean => NUMERIC_TYPES.has(f.field_type)
const isDate = (f: Field): boolean => DATE_TYPES.has(f.field_type)

const fieldOptions = (fields: Field[], predicate?: (f: Field) => boolean) =>
  fields.filter((f) => (predicate ? predicate(f) : true)).map((f) => ({ value: f.name, label: `${f.name}（${f.field_type}）` }))

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
      <span style={{ width: 76, flexShrink: 0, color: 'var(--cn-text-secondary)', fontSize: 12 }}>{label}</span>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  )
}

function ChartForm({ widget, fields, onChange }: {
  widget: Extract<DashboardWidget, { type: 'chart' }>
  fields: Field[]
  onChange: (next: DashboardWidget) => void
}) {
  const chart = widget.chart
  const def = getChartTypeDef(chart.type)
  const supports = def.supports
  const numericOnly = chart.agg !== 'count' || chart.type === 'scatter' || chart.type === 'histogram'
  const xOptions = fieldOptions(fields, chart.type === 'scatter' ? isNumeric : undefined)
  const yOptions = fieldOptions(fields, numericOnly ? isNumeric : undefined)
  const setChart = (patch: Partial<typeof chart>) => onChange({ ...widget, chart: { ...chart, ...patch } })
  const display = widget.display ?? {}
  const setDisplay = (patch: Partial<typeof display>) =>
    onChange({ ...widget, display: { ...display, ...patch } })
  const thresholds = display.thresholds ?? []
  const sortable = SORTABLE_TYPES.has(chart.type)

  const setThreshold = (index: number, patch: Partial<DashboardThreshold>) => {
    setDisplay({ thresholds: thresholds.map((item, i) => (i === index ? { ...item, ...patch } : item)) })
  }

  return (
    <>
      <Row label="图表类型">
        <Select
          value={chart.type}
          options={CHART_TYPE_OPTIONS}
          style={{ width: '100%' }}
          onChange={(type) => {
            const next = getChartTypeDef(type)
            setChart({
              type,
              x: type === 'histogram' || type === 'gauge' ? undefined : chart.x,
              y: next.supports.multiY ? chart.y : chart.y.slice(0, 1),
            })
          }}
          data-testid="dashboard-chart-type"
        />
      </Row>
      {chart.type !== 'histogram' && chart.type !== 'gauge' && (
        <Row label="X 轴">
          <Select
            value={chart.x}
            options={xOptions}
            style={{ width: '100%' }}
            placeholder="选择维度字段"
            onChange={(x) => setChart({ x })}
            data-testid="dashboard-chart-x"
          />
        </Row>
      )}
      <Row label="度量">
        <Select
          mode={supports.multiY ? 'multiple' : undefined}
          value={supports.multiY ? chart.y : chart.y[0]}
          options={yOptions}
          style={{ width: '100%' }}
          placeholder={supports.multiY ? '选择一个或多个数值字段' : '选择数值字段'}
          onChange={(value) => setChart({ y: Array.isArray(value) ? value : value ? [value] : [] })}
          data-testid="dashboard-chart-y"
        />
      </Row>
      {supports.agg && (
        <Row label="聚合">
          <Select
            value={chart.agg}
            options={AGG_OPTIONS}
            style={{ width: '100%' }}
            onChange={(agg) => setChart({ agg })}
          />
        </Row>
      )}
      {supports.series && (
        <Row label="分组字段">
          <Select
            allowClear
            value={chart.series}
            options={fieldOptions(fields)}
            style={{ width: '100%' }}
            placeholder="不分组"
            onChange={(series) => setChart({ series })}
            data-testid="dashboard-chart-series"
          />
        </Row>
      )}
      {supports.stack && (
        <Row label="堆叠">
          <Select
            value={chart.stack}
            options={[
              { value: 'none', label: '不堆叠' },
              { value: 'stack', label: '堆叠' },
              { value: 'percent', label: '百分比堆叠' },
            ]}
            style={{ width: '100%' }}
            onChange={(stack) => setChart({ stack })}
          />
        </Row>
      )}
      {supports.dualAxis && (
        <Row label="双轴">
          <Switch checked={chart.dual_axis} onChange={(dual_axis) => setChart({ dual_axis })} />
        </Row>
      )}
      {chart.type === 'gauge' && (
        <Row label="目标值">
          <InputNumber
            value={chart.target}
            style={{ width: '100%' }}
            placeholder="留空自动取 1.2 倍"
            onChange={(target) => setChart({ target: target ?? undefined })}
            data-testid="dashboard-chart-target"
          />
        </Row>
      )}
      {sortable && (
        <>
          <Row label="排序">
            <Select
              value={chart.sort}
              options={SORT_OPTIONS}
              style={{ width: '100%' }}
              onChange={(sort) => setChart({ sort })}
              data-testid="dashboard-chart-sort"
            />
          </Row>
          <Row label="Top N">
            <InputNumber
              min={1}
              max={100}
              value={chart.top_n}
              style={{ width: '100%' }}
              placeholder="不截断"
              onChange={(top_n) => setChart({ top_n: top_n ?? undefined })}
              data-testid="dashboard-chart-topn"
            />
          </Row>
        </>
      )}
      <Divider style={{ margin: '10px 0' }}>数值格式</Divider>
      <Row label="单位">
        <Input
          value={chart.format.unit ?? ''}
          maxLength={8}
          placeholder="如 元 / %"
          onChange={(e) => setChart({ format: { ...chart.format, unit: e.target.value || undefined } })}
        />
      </Row>
      <Row label="小数位">
        <InputNumber
          min={0}
          max={6}
          value={chart.format.decimals}
          style={{ width: '100%' }}
          onChange={(decimals) => setChart({ format: { ...chart.format, decimals: decimals ?? undefined } })}
        />
      </Row>
      <Divider style={{ margin: '10px 0' }}>配色</Divider>
      <Row label="色板">
        <Select
          value={display.palette ?? 'default'}
          options={Object.keys(PALETTES).map((name) => ({ value: name, label: name }))}
          style={{ width: '100%' }}
          onChange={(palette) => setDisplay({ palette })}
        />
      </Row>
      <Row label="图例">
        <Switch
          checked={display.show_legend !== false}
          onChange={(show_legend) => setDisplay({ show_legend })}
        />
      </Row>
      <Row label="阈值配色">
        <Button
          size="small"
          disabled={thresholds.length >= 5}
          onClick={() => setDisplay({
            thresholds: [...thresholds, {
              value: 0, color: THRESHOLD_COLORS[thresholds.length % THRESHOLD_COLORS.length],
            }].sort((a, b) => a.value - b.value),
          })}
          data-testid="dashboard-chart-threshold-add"
        >
          添加阈值
        </Button>
      </Row>
      {thresholds.map((item, i) => (
        <Row key={`threshold-${i}`} label={`阈值 ${i + 1}`}>
          <Space.Compact style={{ width: '100%' }}>
            <InputNumber
              value={item.value}
              style={{ flex: 1 }}
              onChange={(value) => {
                setDisplay({
                  thresholds: thresholds
                    .map((t, idx) => (idx === i ? { ...t, value: value ?? 0 } : t))
                    .sort((a, b) => a.value - b.value),
                })
              }}
            />
            <Select
              value={item.color}
              style={{ width: 88 }}
              options={THRESHOLD_COLORS.map((color) => ({ value: color, label: color }))}
              onChange={(color) => setThreshold(i, { color })}
            />
            <Button
              danger
              onClick={() => setDisplay({
                thresholds: thresholds.filter((_, idx) => idx !== i),
              })}
            >
              删除
            </Button>
          </Space.Compact>
        </Row>
      ))}
      <Row label="行数上限">
        <InputNumber
          min={1}
          max={5000}
          value={widget.query.limit ?? 2000}
          style={{ width: '100%' }}
          onChange={(limit) => onChange({
            ...widget,
            query: { ...widget.query, ...(limit != null ? { limit } : {}) },
          })}
        />
      </Row>
    </>
  )
}

function KpiForm({ widget, fields, onChange }: {
  widget: Extract<DashboardWidget, { type: 'kpi' }>
  fields: Field[]
  onChange: (next: DashboardWidget) => void
}) {
  const kpi = widget.kpi
  const valueNumeric = kpi.value.agg !== 'count'
  const dateFields = fields.filter(isDate)
  const setKpi = (next: typeof kpi) => onChange({ ...widget, kpi: next })
  return (
    <>
      <Row label="指标字段">
        <Select
          value={kpi.value.field}
          options={fieldOptions(fields, valueNumeric ? isNumeric : undefined)}
          style={{ width: '100%' }}
          onChange={(field) => setKpi({ ...kpi, value: { ...kpi.value, field } })}
          data-testid="dashboard-kpi-field"
        />
      </Row>
      <Row label="聚合">
        <Select
          value={kpi.value.agg}
          options={AGG_OPTIONS}
          style={{ width: '100%' }}
          onChange={(agg) => setKpi({ ...kpi, value: { ...kpi.value, agg } })}
        />
      </Row>
      <Row label="同比/环比">
        <Switch
          checked={!!kpi.compare}
          disabled={!dateFields.length}
          onChange={(checked) => {
            if (!checked) {
              setKpi({ ...kpi, compare: undefined })
              return
            }
            setKpi({
              ...kpi,
              compare: { mode: 'prev_period', date_field: dateFields[0].name, granularity: 'month' },
            })
          }}
        />
      </Row>
      {kpi.compare && (
        <>
          <Row label="日期字段">
            <Select
              value={kpi.compare.date_field}
              options={fieldOptions(fields, isDate)}
              style={{ width: '100%' }}
              onChange={(date_field) => setKpi({ ...kpi, compare: { ...kpi.compare!, date_field } })}
            />
          </Row>
          <Row label="对比方式">
            <Select
              value={kpi.compare.mode}
              options={[
                { value: 'prev_period', label: '环比上一周期' },
                { value: 'prev_year', label: '同比去年同期' },
              ]}
              style={{ width: '100%' }}
              onChange={(mode) => setKpi({ ...kpi, compare: { ...kpi.compare!, mode } })}
            />
          </Row>
          <Row label="时间粒度">
            <Select
              value={kpi.compare.granularity}
              options={GRANULARITY_OPTIONS}
              style={{ width: '100%' }}
              onChange={(granularity) => setKpi({ ...kpi, compare: { ...kpi.compare!, granularity } })}
            />
          </Row>
        </>
      )}
      <Row label="迷你趋势">
        <Switch
          checked={!!kpi.sparkline}
          onChange={(checked) => {
            if (!checked) {
              setKpi({ ...kpi, sparkline: undefined })
              return
            }
            setKpi({
              ...kpi,
              sparkline: { field: kpi.value.field, agg: 'count', points: 12 },
            })
          }}
        />
      </Row>
      {kpi.sparkline && (
        <>
          <Row label="趋势字段">
            <Select
              value={kpi.sparkline.field}
              options={fieldOptions(fields)}
              style={{ width: '100%' }}
              onChange={(field) => setKpi({ ...kpi, sparkline: { ...kpi.sparkline!, field } })}
            />
          </Row>
          <Row label="趋势点数">
            <InputNumber
              min={1}
              max={24}
              value={kpi.sparkline.points}
              style={{ width: '100%' }}
              onChange={(points) => setKpi({
                ...kpi,
                sparkline: { ...kpi.sparkline!, points: points ?? kpi.sparkline!.points },
              })}
            />
          </Row>
        </>
      )}
    </>
  )
}

function TableForm({ widget, fields, onChange }: {
  widget: Extract<DashboardWidget, { type: 'table' }>
  fields: Field[]
  onChange: (next: DashboardWidget) => void
}) {
  return (
    <>
      <Row label="展示列">
        <Select
          mode="multiple"
          maxCount={8}
          value={widget.table.columns}
          options={fieldOptions(fields)}
          style={{ width: '100%' }}
          onChange={(columns) => onChange({ ...widget, table: { ...widget.table, columns } })}
          data-testid="dashboard-table-columns"
        />
      </Row>
      <Row label="行数上限">
        <InputNumber
          min={1}
          max={50}
          value={widget.table.row_limit}
          style={{ width: '100%' }}
          onChange={(row_limit) => onChange({
            ...widget,
            table: { ...widget.table, row_limit: row_limit ?? widget.table.row_limit },
          })}
        />
      </Row>
    </>
  )
}

function DataTab({ widget, fields, onPatchWidget }: {
  widget: DashboardWidget | undefined
  fields: Field[]
  onPatchWidget: (id: string, updater: (w: DashboardWidget) => DashboardWidget) => void
}) {
  if (!widget) return <Empty description="先在「布局」里选中一个组件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  const onChange = (next: DashboardWidget) => onPatchWidget(widget.id, () => next)
  if (widget.type === 'chart') return <ChartForm widget={widget} fields={fields} onChange={onChange} />
  if (widget.type === 'kpi') return <KpiForm widget={widget} fields={fields} onChange={onChange} />
  if (widget.type === 'table') return <TableForm widget={widget} fields={fields} onChange={onChange} />
  return (
    <Input.TextArea
      value={widget.text.content}
      autoSize={{ minRows: 8, maxRows: 20 }}
      maxLength={20000}
      onChange={(e) => onChange({ ...widget, text: { content: e.target.value } })}
      data-testid="dashboard-text-content"
    />
  )
}

export interface DashboardConfigDrawerProps {
  open: boolean
  onClose: () => void
  config: DashboardConfig
  fields: Field[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  onPatchWidget: (id: string, updater: (w: DashboardWidget) => DashboardWidget) => void
  onPatchLayout: (id: string, patch: Partial<WidgetBox>) => void
  onRemoveWidget: (id: string) => void
  onAddWidget: (type: DashboardWidgetType) => void
  onApplyPreset: (preset: LayoutPresetKey) => void
  onUpdateCanvas: (patch: Partial<DashboardConfig['canvas']>) => void
  onUpdateSettings: (patch: Partial<DashboardConfig['settings']>) => void
}

export default function DashboardConfigDrawer({
  open, onClose, config, fields, selectedId, onSelect,
  onPatchWidget, onPatchLayout, onRemoveWidget, onAddWidget, onApplyPreset, onUpdateCanvas, onUpdateSettings,
}: DashboardConfigDrawerProps) {
  const [addType, setAddType] = useState<DashboardWidgetType>('chart')
  const widget = config.widgets.find((w) => w.id === selectedId)

  const layoutTab = (
    <div data-testid="dashboard-drawer-layout">
      <Row label="当前组件">
        <Select
          value={selectedId ?? undefined}
          options={config.widgets.map((w) => ({ value: w.id, label: w.title || DASHBOARD_TYPE_LABELS[w.type] }))}
          style={{ width: '100%' }}
          placeholder="选择组件"
          onChange={(id) => onSelect(id)}
          data-testid="dashboard-drawer-select"
        />
      </Row>
      {widget && (
        <>
          <Space style={{ marginBottom: 10 }} wrap>
            {([
              ['x', 0, DASHBOARD_COLS - 1],
              ['y', 0, 200],
              ['w', 1, DASHBOARD_COLS],
              ['h', 1, DASHBOARD_MAX_H],
            ] as const).map(([key, min, max]) => (
              <div key={key} style={{ width: 120 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{key.toUpperCase()}</Typography.Text>
                <InputNumber
                  min={min}
                  max={max}
                  value={widget.layout[key]}
                  style={{ width: '100%' }}
                  onChange={(value) => {
                    if (value == null) return
                    onPatchLayout(widget.id, { [key]: value })
                  }}
                  data-testid={`dashboard-layout-${key}`}
                />
              </div>
            ))}
          </Space>
          <Button danger block onClick={() => onRemoveWidget(widget.id)} data-testid="dashboard-drawer-remove">
            删除当前组件
          </Button>
        </>
      )}
      <Divider style={{ margin: '14px 0' }}>版式预设</Divider>
      <Space wrap>
        {DASHBOARD_PRESETS.map((preset) => (
          <Button key={preset.key} size="small" onClick={() => onApplyPreset(preset.key)}>
            {preset.label}
          </Button>
        ))}
      </Space>
      <Divider style={{ margin: '14px 0' }}>添加组件</Divider>
      <Space.Compact style={{ width: '100%' }}>
        <Select
          value={addType}
          style={{ flex: 1 }}
          options={(Object.keys(DASHBOARD_TYPE_LABELS) as DashboardWidgetType[])
            .map((type) => ({ value: type, label: DASHBOARD_TYPE_LABELS[type] }))}
          onChange={(type) => setAddType(type)}
        />
        <Button
          type="primary"
          disabled={!fields.length || config.widgets.length >= 32}
          onClick={() => onAddWidget(addType)}
          data-testid="dashboard-drawer-add"
        >
          添加
        </Button>
      </Space.Compact>
    </div>
  )

  const appearanceTab = (
    <div data-testid="dashboard-drawer-appearance">
      {widget && (
        <Row label="组件标题">
          <Input
            value={widget.title ?? ''}
            maxLength={200}
            placeholder={DASHBOARD_TYPE_LABELS[widget.type]}
            onChange={(e) => onPatchWidget(widget.id, (w) => ({ ...w, title: e.target.value || undefined }))}
            data-testid="dashboard-widget-title"
          />
        </Row>
      )}
      <Divider style={{ margin: '10px 0 14px' }}>画布</Divider>
      <Row label="行高（px）">
        <InputNumber
          min={20}
          max={80}
          value={config.canvas.row_height}
          style={{ width: '100%' }}
          onChange={(row_height) => row_height != null && onUpdateCanvas({ row_height })}
        />
      </Row>
      <Row label="间距（px）">
        <InputNumber
          min={0}
          max={32}
          value={config.canvas.gap}
          style={{ width: '100%' }}
          onChange={(gap) => gap != null && onUpdateCanvas({ gap })}
        />
      </Row>
      <Row label="内边距（px）">
        <InputNumber
          min={0}
          max={48}
          value={config.canvas.padding}
          style={{ width: '100%' }}
          onChange={(padding) => padding != null && onUpdateCanvas({ padding })}
        />
      </Row>
      <Row label="主题">
        <Select
          value={config.settings.theme}
          options={[
            { value: 'inherit', label: '跟随系统' },
            { value: 'light', label: '浅色' },
            { value: 'dark', label: '深色' },
          ]}
          style={{ width: '100%' }}
          onChange={(theme) => onUpdateSettings({ theme })}
        />
      </Row>
    </div>
  )

  return (
    <Drawer
      title="画布属性"
      open={open}
      onClose={onClose}
      width={360}
      destroyOnHidden
      data-testid="dashboard-config-drawer"
    >
      <Tabs
        items={[
          { key: 'layout', label: '布局', children: layoutTab },
          { key: 'data', label: '数据', children: <DataTab widget={widget} fields={fields} onPatchWidget={onPatchWidget} /> },
          { key: 'appearance', label: '外观', children: appearanceTab },
        ]}
      />
    </Drawer>
  )
}

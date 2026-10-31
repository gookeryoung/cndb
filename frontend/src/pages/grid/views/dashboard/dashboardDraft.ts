/** dashboard 编辑草稿与撤销栈（ADR 0023 P1）.
 *
 * 纯函数：所有变更都返回新的 `DashboardConfig`，由 `useDashboardDraft` 包一层
 * `useState`。撤销采用「快照栈」（≤50 步），比操作日志简单，32 块内存可控。
 */

import type { Field } from '@/api'
import {
  MAX_DASHBOARD_WIDGETS,
  type DashboardCanvas,
  type DashboardConfig,
  type DashboardWidget,
  type DashboardWidgetType,
} from './dashboardModel'
import { DASHBOARD_COLS, DASHBOARD_MAX_H, applyPreset, findFreeSlot, type LayoutPresetKey, type WidgetBox } from './dashboardLayout'

/** 撤销栈上限（ADR 0023 §2） */
export const DRAFT_HISTORY_LIMIT = 50

export interface DraftHistory {
  present: DashboardConfig
  past: DashboardConfig[]
  future: DashboardConfig[]
}

const NUMERIC_TYPES = new Set(['number', 'float', 'percentage', 'timestamp'])

/** 默认新增块尺寸：KPI 矮、图表高、文本/明细中等 */
const DEFAULT_SIZE: Record<DashboardWidgetType, { w: number; h: number }> = {
  chart: { w: 6, h: 8 },
  kpi: { w: 3, h: 4 },
  table: { w: 6, h: 6 },
  text: { w: 4, h: 4 },
}

export function createHistory(config: DashboardConfig): DraftHistory {
  return { present: config, past: [], future: [] }
}

/** 提交一次变更；与当前快照相同则不变更（避免空撤销步） */
export function commitHistory(
  history: DraftHistory,
  next: DashboardConfig,
  limit: number = DRAFT_HISTORY_LIMIT,
): DraftHistory {
  if (sameConfig(history.present, next)) return history
  return {
    present: next,
    past: [...history.past, history.present].slice(-limit),
    future: [],
  }
}

export function undoHistory(history: DraftHistory): DraftHistory {
  const previous = history.past.at(-1)
  if (!previous) return history
  return {
    present: previous,
    past: history.past.slice(0, -1),
    future: [history.present, ...history.future].slice(0, DRAFT_HISTORY_LIMIT),
  }
}

export function redoHistory(history: DraftHistory): DraftHistory {
  const [next, ...rest] = history.future
  if (!next) return history
  return {
    present: next,
    past: [...history.past, history.present].slice(-DRAFT_HISTORY_LIMIT),
    future: rest,
  }
}

/** 结构相等（键序无关的 JSON 比较即可，配置体积有限） */
export function sameConfig(a: DashboardConfig, b: DashboardConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** 草稿相对基线是否有未保存变更 */
export function isDirty(present: DashboardConfig, baseline: DashboardConfig): boolean {
  return !sameConfig(present, baseline)
}

/** 把布局坐标写回 widgets（按 id 对齐，未知 id 忽略） */
export function withLayouts(config: DashboardConfig, boxes: WidgetBox[]): DashboardConfig {
  const byId = new Map(boxes.map((b) => [b.id, b]))
  return {
    ...config,
    widgets: config.widgets.map((w) => {
      const layout = byId.get(w.id)
      return layout ? { ...w, layout: { ...layout, id: w.id } } : w
    }),
  }
}

/** 生成不重复的 widget id（`w_<type>_<n>`） */
export function nextWidgetId(config: DashboardConfig, type: DashboardWidgetType): string {
  const prefix = `w_${type}_`
  let index = 1
  while (config.widgets.some((w) => w.id === `${prefix}${index}`)) index += 1
  return `${prefix}${index}`
}

const isNumeric = (f: Field): boolean => NUMERIC_TYPES.has(f.field_type)

function firstField(fields: Field[], predicate?: (f: Field) => boolean): Field | undefined {
  return fields.find((f) => (predicate ? predicate(f) : true)) ?? fields[0]
}

/** 按表字段生成一个新 widget（字段为空时返回 null，由 UI 禁用添加入口） */
export function buildWidget(
  type: DashboardWidgetType,
  fields: Field[],
  layout: WidgetBox,
): DashboardWidget | null {
  if (!fields.length) return null
  const base = layout
  switch (type) {
    case 'chart': {
      const numeric = firstField(fields, isNumeric)
      const dimension = firstField(fields, (f) => !isNumeric(f)) ?? fields[0]
      const measure = numeric ?? dimension
      return {
        id: layout.id,
        type: 'chart',
        layout: base,
        query: { filters: [], filter_logic: 'AND', sortings: [] },
        chart: {
          type: 'bar',
          x: dimension.name,
          y: [measure.name],
          agg: numeric ? 'sum' : 'count',
          stack: 'none',
          sort: 'none',
          dual_axis: false,
          format: {},
        },
      }
    }
    case 'kpi': {
      const numeric = firstField(fields, isNumeric)
      const value = numeric ?? fields[0]
      return {
        id: layout.id,
        type: 'kpi',
        layout: base,
        query: { filters: [], filter_logic: 'AND', sortings: [] },
        kpi: { value: { field: value.name, agg: numeric ? 'sum' : 'count' } },
      }
    }
    case 'table': {
      const columns = fields.slice(0, 3).map((f) => f.name)
      return {
        id: layout.id,
        type: 'table',
        layout: base,
        query: { filters: [], filter_logic: 'AND', sortings: [] },
        table: { columns, row_limit: 20 },
      }
    }
    case 'text':
      return {
        id: layout.id,
        type: 'text',
        layout: base,
        query: { filters: [], filter_logic: 'AND', sortings: [] },
        text: { content: '在此填写画布说明。' },
      }
  }
}

/** 追加一个 widget 到首个空位 */
export function addWidget(
  config: DashboardConfig,
  type: DashboardWidgetType,
  fields: Field[],
): DashboardConfig {
  if (config.widgets.length >= MAX_DASHBOARD_WIDGETS) return config
  const size = DEFAULT_SIZE[type]
  const slot = findFreeSlot(config.widgets.map((w) => w.layout), size.w, size.h, config.canvas.cols)
  const id = nextWidgetId(config, type)
  const widget = buildWidget(type, fields, { id, ...slot, ...size })
  if (!widget) return config
  return { ...config, widgets: [...config.widgets, widget] }
}

export function removeWidget(config: DashboardConfig, id: string): DashboardConfig {
  return { ...config, widgets: config.widgets.filter((w) => w.id !== id) }
}

/** 用 updater 替换单个 widget；id 不匹配时原样返回 */
export function patchWidget(
  config: DashboardConfig,
  id: string,
  updater: (widget: DashboardWidget) => DashboardWidget,
): DashboardConfig {
  const index = config.widgets.findIndex((w) => w.id === id)
  if (index < 0) return config
  const widgets = [...config.widgets]
  widgets[index] = updater(widgets[index])
  return { ...config, widgets }
}

/** 更新画布外观参数 */
export function patchCanvas(config: DashboardConfig, patch: Partial<DashboardCanvas>): DashboardConfig {
  return { ...config, canvas: { ...config.canvas, ...patch } }
}

/** 更新主题设置 */
export function patchSettings(
  config: DashboardConfig,
  patch: Partial<DashboardConfig['settings']>,
): DashboardConfig {
  return { ...config, settings: { ...config.settings, ...patch } }
}

/** 应用版式预设（只改布局，不增删内容） */
export function applyLayoutPreset(config: DashboardConfig, preset: LayoutPresetKey): DashboardConfig {
  const boxes = applyPreset(preset, config.widgets.map((w) => w.layout), config.canvas.cols || DASHBOARD_COLS)
  return withLayouts(config, boxes)
}

/** 新增块的默认高度上限（供 UI 预览/提示，避免超过 20 格） */
export function defaultWidgetHeight(type: DashboardWidgetType): number {
  return Math.min(DEFAULT_SIZE[type].h, DASHBOARD_MAX_H)
}

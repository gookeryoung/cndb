/** dashboard 草稿与撤销栈纯函数测试（ADR 0023 P1）.
 *
 * 覆盖：快照栈提交/去重/上限/undo/redo · 脏检查 · 布局写回 · id 生成 ·
 * 四类 widget 默认构造 · 空位添加与 32 块上限 · 删除/改块/画布/设置/预设。
 */

import { describe, expect, it } from 'vitest'
import type { Field } from '@/api'
import { makeField } from '@/test/fixtures'
import {
  MAX_DASHBOARD_WIDGETS,
  type DashboardConfig,
  type DashboardWidget,
} from './dashboardModel'
import {
  addWidget,
  applyLayoutPreset,
  buildWidget,
  commitHistory,
  createHistory,
  defaultWidgetHeight,
  isDirty,
  nextWidgetId,
  patchCanvas,
  patchSettings,
  patchWidget,
  removeWidget,
  sameConfig,
  undoHistory,
  redoHistory,
  withLayouts,
} from './dashboardDraft'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '商品类别', field_type: 'text' }),
  makeField({ id: 2, name: '销售额', field_type: 'number' }),
  makeField({ id: 3, name: '日期', field_type: 'date' }),
]

function makeConfig(overrides?: Partial<DashboardConfig>): DashboardConfig {
  return {
    schema_version: 1,
    canvas: { cols: 12, row_height: 40, gap: 12, padding: 16 },
    widgets: [],
    global_filters: [],
    settings: { refresh_interval: 0, theme: 'inherit' },
    ...overrides,
  }
}

function makeWidget(id: string, x: number, y: number, w = 6, h = 4): DashboardWidget {
  return {
    id,
    type: 'text',
    layout: { id, x, y, w, h },
    query: { filters: [], filter_logic: 'AND', sortings: [] },
    text: { content: `${id} 说明` },
  }
}

describe('dashboardDraft 撤销栈', () => {
  const base = makeConfig()

  it('createHistory 初始化：present 为基线，无历史', () => {
    const history = createHistory(base)
    expect(history.present).toEqual(base)
    expect(history.past).toEqual([])
    expect(history.future).toEqual([])
  })

  it('commitHistory 相同配置不产生新撤销步', () => {
    const history = createHistory(base)
    expect(commitHistory(history, structuredClone(base))).toBe(history)
  })

  it('commitHistory 记录上一快照并清空 redo', () => {
    const history = createHistory(base)
    const first = commitHistory(history, patchCanvas(base, { gap: 8 }))
    expect(first.present.canvas.gap).toBe(8)
    expect(first.past).toHaveLength(1)
    expect(first.past[0]).toBe(base)
    expect(first.future).toEqual([])
  })

  it('commitHistory 超过上限时丢弃最早快照', () => {
    let history = createHistory(base)
    for (let i = 1; i <= 55; i += 1) {
      history = commitHistory(history, patchCanvas(history.present, { gap: i }), 50)
    }
    expect(history.past).toHaveLength(50)
    // 最早保留的是第 5 次提交前的快照（gap=5）
    expect(history.past[0].canvas.gap).toBe(5)
  })

  it('undoHistory 回到上一快照并把当前压入 future；空栈幂等', () => {
    const history = commitHistory(createHistory(base), patchCanvas(base, { gap: 8 }))
    const undone = undoHistory(history)
    expect(undone.present).toBe(base)
    expect(undone.future[0].canvas.gap).toBe(8)
    expect(undoHistory(undone)).toBe(undone)
  })

  it('redoHistory 恢复被撤销的快照；空栈幂等', () => {
    const history = commitHistory(createHistory(base), patchCanvas(base, { gap: 8 }))
    const undone = undoHistory(history)
    const redone = redoHistory(undone)
    expect(redone.present.canvas.gap).toBe(8)
    expect(redone.past).toHaveLength(1)
    expect(redoHistory(redone)).toBe(redone)
  })

  it('撤销后提交新变更会清空 future（不保留旧分支）', () => {
    const history = commitHistory(createHistory(base), patchCanvas(base, { gap: 8 }))
    const undone = undoHistory(history)
    const branched = commitHistory(undone, patchCanvas(undone.present, { gap: 20 }))
    expect(branched.future).toEqual([])
    expect(branched.present.canvas.gap).toBe(20)
  })
})

describe('dashboardDraft 脏检查与布局写回', () => {
  const base = makeConfig()

  it('sameConfig / isDirty 按结构比较', () => {
    expect(sameConfig(base, structuredClone(base))).toBe(true)
    expect(isDirty(base, patchCanvas(base, { gap: 9 }))).toBe(true)
    expect(isDirty(patchCanvas(base, { gap: 9 }), patchCanvas(base, { gap: 9 }))).toBe(false)
  })

  it('withLayouts 按 id 写回坐标，未知 id 忽略', () => {
    const config = makeConfig({ widgets: [makeWidget('a', 0, 0), makeWidget('b', 6, 0)] })
    const next = withLayouts(config, [
      { id: 'b', x: 0, y: 0, w: 12, h: 4 },
      { id: 'ghost', x: 0, y: 10, w: 1, h: 1 },
    ])
    expect(next.widgets[1].layout).toEqual({ id: 'b', x: 0, y: 0, w: 12, h: 4 })
    expect(next.widgets[0].layout).toEqual(config.widgets[0].layout)
    expect(next.widgets).toHaveLength(2)
  })
})

describe('dashboardDraft 新增组件', () => {
  it('nextWidgetId 生成不重复的 w_<type>_<n>', () => {
    const config = makeConfig({ widgets: [makeWidget('w_text_1', 0, 0)] })
    expect(nextWidgetId(config, 'text')).toBe('w_text_2')
    expect(nextWidgetId(config, 'chart')).toBe('w_chart_1')
  })

  it('buildWidget 无字段时返回 null', () => {
    expect(buildWidget('text', [], { id: 'w', x: 0, y: 0, w: 4, h: 4 })).toBeNull()
  })

  it('buildWidget 图表默认首个数值字段为度量、首个非数值字段为维度', () => {
    const widget = buildWidget('chart', FIELDS, { id: 'c', x: 0, y: 0, w: 6, h: 8 })
    expect(widget?.type).toBe('chart')
    if (widget?.type !== 'chart') throw new Error('unreachable')
    expect(widget.chart.x).toBe('商品类别')
    expect(widget.chart.y).toEqual(['销售额'])
    expect(widget.chart.agg).toBe('sum')
    expect(widget.chart.type).toBe('bar')
  })

  it('buildWidget KPI 默认首个数值字段求和', () => {
    const widget = buildWidget('kpi', FIELDS, { id: 'k', x: 0, y: 0, w: 3, h: 4 })
    if (widget?.type !== 'kpi') throw new Error('unreachable')
    expect(widget.kpi.value).toEqual({ field: '销售额', agg: 'sum' })
  })

  it('buildWidget 明细默认前 3 列与行数上限 20', () => {
    const widget = buildWidget('table', FIELDS, { id: 't', x: 0, y: 0, w: 6, h: 6 })
    if (widget?.type !== 'table') throw new Error('unreachable')
    expect(widget.table.columns).toEqual(['商品类别', '销售额', '日期'])
    expect(widget.table.row_limit).toBe(20)
  })

  it('buildWidget 文本默认说明文案', () => {
    const widget = buildWidget('text', FIELDS, { id: 'x', x: 0, y: 0, w: 4, h: 4 })
    if (widget?.type !== 'text') throw new Error('unreachable')
    expect(widget.text.content).toBe('在此填写画布说明。')
  })

  it('addWidget 放到首个空位并追加到末尾', () => {
    const config = makeConfig({ widgets: [makeWidget('a', 0, 0, 6, 4)] })
    const next = addWidget(config, 'text', FIELDS)
    expect(next.widgets).toHaveLength(2)
    const added = next.widgets[1]
    expect(added.type).toBe('text')
    // 右侧空位（x=6, y=0, 4×4）
    expect(added.layout).toMatchObject({ x: 6, y: 0, w: 4, h: 4 })
  })

  it('addWidget 达到 32 块上限时原样返回', () => {
    const widgets = Array.from({ length: MAX_DASHBOARD_WIDGETS }, (_, i) => makeWidget(`w${i}`, 0, i * 4))
    const config = makeConfig({ widgets })
    expect(addWidget(config, 'text', FIELDS)).toBe(config)
  })

  it('defaultWidgetHeight 不超过 20 格', () => {
    expect(defaultWidgetHeight('chart')).toBe(8)
    expect(defaultWidgetHeight('kpi')).toBe(4)
  })
})

describe('dashboardDraft 变更操作', () => {
  it('removeWidget 剔除指定块', () => {
    const config = makeConfig({ widgets: [makeWidget('a', 0, 0), makeWidget('b', 0, 4)] })
    const next = removeWidget(config, 'a')
    expect(next.widgets.map((w) => w.id)).toEqual(['b'])
  })

  it('patchWidget 只替换命中的块，未命中原样返回', () => {
    const config = makeConfig({ widgets: [makeWidget('a', 0, 0), makeWidget('b', 0, 4)] })
    const next = patchWidget(config, 'a', (w) => ({ ...w, title: '改了' }))
    expect(next.widgets[0].title).toBe('改了')
    expect(next.widgets[1]).toBe(config.widgets[1])
    expect(patchWidget(config, 'ghost', (w) => w)).toBe(config)
  })

  it('patchCanvas / patchSettings 合并指定字段', () => {
    const config = makeConfig()
    expect(patchCanvas(config, { gap: 20 }).canvas).toEqual({ ...config.canvas, gap: 20 })
    expect(patchSettings(config, { theme: 'dark' }).settings.theme).toBe('dark')
  })

  it('applyLayoutPreset 按 4 个 KPI 生成顶栏 + 图表两列且无重叠', () => {
    const widgets = [
      makeWidget('k1', 0, 0, 3, 4),
      makeWidget('k2', 3, 0, 3, 4),
      makeWidget('k3', 6, 0, 3, 4),
      makeWidget('k4', 9, 0, 3, 4),
      makeWidget('c1', 0, 4, 6, 8),
      makeWidget('c2', 6, 4, 6, 8),
    ]
    const next = applyLayoutPreset(makeConfig({ widgets }), 'kpi-charts')
    expect(next.widgets).toHaveLength(6)
    expect(next.widgets[0].layout).toMatchObject({ x: 0, y: 0, w: 3, h: 4 })
    expect(next.widgets[4].layout).toMatchObject({ x: 0, y: 4, w: 6, h: 8 })
    expect(next.widgets[5].layout).toMatchObject({ x: 6, y: 4, w: 6, h: 8 })
    // 无重叠
    const boxes = next.widgets.map((w) => w.layout)
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i]
        const b = boxes[j]
        const overlap = a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
        expect(overlap).toBe(false)
      }
    }
  })
})

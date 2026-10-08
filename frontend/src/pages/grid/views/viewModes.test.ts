/** viewModes 纯函数单元测试 — 模式按钮组推导（对应 E2E view-mode-switch 矩阵的下沉等价覆盖） */
import { describe, it, expect } from 'vitest'
import { VALID_MODES, collectAvailableViewTypes, deriveModeSwitch, type ViewMode } from './viewModes'

/** 与 GridPage.MODE_BUTTONS 同序的测试替身（不含 icon） */
const ALL_BUTTONS: Array<{ mode: ViewMode }> = [
  { mode: 'grid' }, { mode: 'kanban' },
  { mode: 'calendar' }, { mode: 'gantt' }, { mode: 'wbs' }, { mode: 'matrix' }, { mode: 'chart' },
]

/** 快捷构造视图（view_type 合法值） */
function view(...types: string[]): Array<{ view_type: string }> {
  return types.map((view_type) => ({ view_type }))
}

describe('collectAvailableViewTypes', () => {
  it('grid 始终存在，即使 views 为空', () => {
    expect([...collectAvailableViewTypes([])]).toEqual(['grid'])
  })

  it('非法 view_type 被过滤', () => {
    const s = collectAvailableViewTypes(view('bogus', 'kanban'))
    expect(s.has('bogus' as ViewMode)).toBe(false)
    expect(s.has('grid')).toBe(true)
    expect(s.has('kanban')).toBe(true)
  })

  it('去重并保留全部合法类型', () => {
    const s = collectAvailableViewTypes(view('kanban', 'kanban', 'gantt'))
    expect(s.size).toBe(3) // grid + kanban + gantt
  })
})

describe('deriveModeSwitch — 模式按钮组矩阵（与 E2E seed 数据 1:1）', () => {
  it('部门表（仅 grid 视图）→ 按钮组隐藏（E2E 断言 0 个按钮）', () => {
    const { buttons, visible } = deriveModeSwitch(view('grid'), ALL_BUTTONS)
    expect(visible).toBe(false)
    expect(buttons).toEqual([{ mode: 'grid' }])
  })

  it('科研项目（grid+kanban+chart）→ 3 个按钮', () => {
    const { buttons, visible } = deriveModeSwitch(view('grid', 'kanban', 'chart'), ALL_BUTTONS)
    expect(visible).toBe(true)
    expect(buttons.map((b) => b.mode)).toEqual(['grid', 'kanban', 'chart'])
  })

  it('项目进展（grid+kanban+calendar+chart）→ 4 个按钮', () => {
    const { buttons, visible } = deriveModeSwitch(
      view('grid', 'kanban', 'calendar', 'chart'), ALL_BUTTONS,
    )
    expect(visible).toBe(true)
    expect(buttons).toHaveLength(4)
  })

  it('WBS任务分解（grid+kanban+calendar+gantt+wbs+chart）→ 6 个按钮', () => {
    const { buttons, visible } = deriveModeSwitch(
      view('grid', 'kanban', 'calendar', 'gantt', 'wbs', 'chart'), ALL_BUTTONS,
    )
    expect(visible).toBe(true)
    expect(buttons.map((b) => b.mode)).toEqual(['grid', 'kanban', 'calendar', 'gantt', 'wbs', 'chart'])
  })

  it('产品开发（grid+kanban+calendar+gantt+chart，缺 wbs/matrix）→ 5 个按钮', () => {
    const { buttons, visible } = deriveModeSwitch(
      view('grid', 'kanban', 'calendar', 'gantt', 'chart'), ALL_BUTTONS,
    )
    expect(visible).toBe(true)
    expect(buttons).toHaveLength(5)
    expect(buttons.some((b) => b.mode === 'wbs')).toBe(false)
    expect(buttons.some((b) => b.mode === 'matrix')).toBe(false)
  })

  it('气温天气（grid+kanban+calendar+matrix+chart）→ 含 matrix 按钮（seed 2026-10 补充）', () => {
    const { buttons, visible } = deriveModeSwitch(
      view('grid', 'kanban', 'calendar', 'matrix', 'chart'), ALL_BUTTONS,
    )
    expect(visible).toBe(true)
    expect(buttons.some((b) => b.mode === 'matrix')).toBe(true)
  })
})

describe('VALID_MODES', () => {
  it('与 7 种模式一一对应（URL/storage 校验共用）', () => {
    expect(VALID_MODES).toEqual(['grid', 'kanban', 'calendar', 'gantt', 'wbs', 'matrix', 'chart'])
  })
})

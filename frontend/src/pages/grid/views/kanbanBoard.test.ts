/** kanbanBoard 纯函数单元测试 — 紧急级别/优先级/比较器/排序/分组聚合 */
import { describe, it, expect } from 'vitest'
import type { RowResponse, Field } from '@/api'
import { makeField } from '@/test/fixtures'
import {
  getUrgencyRank, getPriorityRank, compareField, sortKanbanCards,
  resolveGroupField, groupKanbanColumns, resolveDoneCtx, isDoneRow,
  buildDoneToggleValue,
} from './kanbanBoard'

/** 构造相对今天偏移 N 天的 'YYYY-MM-DD' 日期串（getUrgencyRank 依赖当前时间，动态构造保证用例稳定） */
function dateStr(offsetDays: number): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 快捷构造行记录（默认带 created_at 便于排序兜底用例） */
function makeRow(overrides: Record<string, unknown> & { id: number }): RowResponse {
  return { created_at: '2026-01-01T00:00:00', ...overrides } as RowResponse
}

// ── 共享字段定义 ──────────────────────────────────────

const statusField = makeField({
  id: 1, name: '状态', field_type: 'select',
  config: {
    options: [
      { value: 'todo', label: '待办' },
      { value: 'doing', label: '进行中' },
      { value: 'done', label: '已完成' },
    ]
  },
})
const scoreField = makeField({ id: 2, name: '分数', field_type: 'number' })
const dueField = makeField({ id: 3, name: '截止', field_type: 'date' })
const tagsField = makeField({
  id: 4, name: '标签', field_type: 'multi_select',
  config: { options: [{ value: 'fe', label: '前端' }, { value: 'be', label: '后端' }] },
})
const linkField = makeField({ id: 5, name: '所属', field_type: 'link' })

const fields: Field[] = [statusField, scoreField, dueField, tagsField, linkField]

// ── getUrgencyRank ────────────────────────────────────

describe('getUrgencyRank', () => {
  it('未配置截止字段返回 0', () => {
    expect(getUrgencyRank(makeRow({ id: 1 }), undefined, 3)).toBe(0)
  })

  it('截止值为空返回 0', () => {
    expect(getUrgencyRank(makeRow({ id: 1, 截止: null }), '截止', 3)).toBe(0)
  })

  it('已逾期（昨天）返回 2', () => {
    expect(getUrgencyRank(makeRow({ id: 1, 截止: dateStr(-1) }), '截止', 3)).toBe(2)
  })

  it('阈值内（明天）返回 1', () => {
    expect(getUrgencyRank(makeRow({ id: 1, 截止: dateStr(1) }), '截止', 3)).toBe(1)
  })

  it('远期（30 天后）返回 0', () => {
    expect(getUrgencyRank(makeRow({ id: 1, 截止: dateStr(30) }), '截止', 3)).toBe(0)
  })
})

// ── getPriorityRank ───────────────────────────────────

describe('getPriorityRank', () => {
  it('无字段或无 config 返回 0', () => {
    expect(getPriorityRank(makeRow({ id: 1 }), undefined, 'todo')).toBe(0)
    expect(getPriorityRank(makeRow({ id: 1 }), makeField({ id: 9, name: 'x', field_type: 'select' }), 'todo')).toBe(0)
  })

  it('options 索引越小权重越大（value 匹配）', () => {
    // 'doing' 在 options 中索引 1，长度 3 → 权重 2
    expect(getPriorityRank(makeRow({ id: 1 }), statusField, 'doing')).toBe(2)
  })

  it('按 label 匹配', () => {
    expect(getPriorityRank(makeRow({ id: 1 }), statusField, '待办')).toBe(3)
  })

  it('值不在 options 中返回 0', () => {
    expect(getPriorityRank(makeRow({ id: 1 }), statusField, 'unknown')).toBe(0)
  })
})

// ── compareField ──────────────────────────────────────

describe('compareField', () => {
  it('number 字段按数值比较（字符串比较会得到错误结果）', () => {
    const a = makeRow({ id: 1, 分数: 2 })
    const b = makeRow({ id: 2, 分数: 10 })
    expect(compareField(a, b, '分数', fields, 'asc')).toBeLessThan(0)
  })

  it('空值（null/undefined/空串）排在末尾', () => {
    const a = makeRow({ id: 1, 分数: 5 })
    const b = makeRow({ id: 2, 分数: null })
    expect(compareField(b, a, '分数', fields, 'asc')).toBe(1)
    expect(compareField(a, b, '分数', fields, 'asc')).toBe(-1)
    expect(compareField(b, b, '分数', fields, 'asc')).toBe(0)
  })

  it('date 字段按时间先后比较', () => {
    const a = makeRow({ id: 1, 截止: '2026-01-01' })
    const b = makeRow({ id: 2, 截止: '2026-06-01' })
    expect(compareField(a, b, '截止', fields, 'asc')).toBeLessThan(0)
  })

  it('文本字段按 zh-CN 拼音比较', () => {
    const a = makeRow({ id: 1, 名称: '张三' })
    const b = makeRow({ id: 2, 名称: '李四' })
    expect(compareField(a, b, '名称', fields, 'asc')).toBeGreaterThan(0)
  })

  it('desc 方向取反', () => {
    const a = makeRow({ id: 1, 分数: 2 })
    const b = makeRow({ id: 2, 分数: 10 })
    expect(compareField(a, b, '分数', fields, 'desc')).toBeGreaterThan(0)
  })
})

// ── sortKanbanCards ───────────────────────────────────

describe('sortKanbanCards', () => {
  it('紧急置顶：逾期 > 紧急 > 正常', () => {
    const rows = [
      makeRow({ id: 1, 截止: dateStr(30) }), // 正常
      makeRow({ id: 2, 截止: dateStr(-1) }), // 逾期
      makeRow({ id: 3, 截止: dateStr(1) }), // 紧急
    ]
    const sorted = sortKanbanCards(rows, fields, {
      urgent_threshold_days: 3, due_date_field: '截止', pin_urgent: true,
    })
    expect(sorted.map(r => r.id)).toEqual([2, 3, 1])
  })

  it('pin_urgent=false 时关闭置顶', () => {
    const rows = [
      makeRow({ id: 1, created_at: '2026-01-01T00:00:00', 截止: dateStr(-1) }), // 逾期但 created 更早
      makeRow({ id: 2, created_at: '2026-05-01T00:00:00', 截止: dateStr(30) }),
    ]
    const sorted = sortKanbanCards(rows, fields, {
      urgent_threshold_days: 3, due_date_field: '截止', pin_urgent: false,
    })
    // 无排序键时走 created_at 倒序兜底：逾期卡 created 更早被排后，证明置顶未参与
    expect(sorted.map(r => r.id)).toEqual([2, 1])
  })

  it('card_sort_field 数字降序排序', () => {
    const rows = [
      makeRow({ id: 1, 分数: 10 }),
      makeRow({ id: 2, 分数: 99 }),
      makeRow({ id: 3, 分数: 42 }),
    ]
    const sorted = sortKanbanCards(rows, fields, {
      urgent_threshold_days: 3, card_sort_field: '分数', card_sort_direction: 'desc',
    })
    expect(sorted.map(r => r.id)).toEqual([2, 3, 1])
  })

  it('级联 view_sortings 并与 card_sort_field 去重', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'doing', 分数: 1 }),
      makeRow({ id: 2, 状态: 'doing', 分数: 2 }),
      makeRow({ id: 3, 状态: 'todo', 分数: 9 }),
    ]
    // card_sort_field=状态（文本 asc：doing < todo）+ view_sortings 里重复的 状态 被去重
    // 若未去重，'状态' desc 会二次参与导致 todo 在前；实际结果 [1,2,3] 证明去重生效
    const sorted = sortKanbanCards(rows, fields, {
      urgent_threshold_days: 3, card_sort_field: '状态', card_sort_direction: 'asc',
    }, [
      { field_name: '状态', direction: 'desc' }, // 应被去重忽略
      { field_name: '分数', direction: 'asc' },
    ])
    expect(sorted.map(r => r.id)).toEqual([1, 2, 3])
  })

  it('优先级权重兜底：options 靠前的值排前', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'doing' }), // 权重 2
      makeRow({ id: 2, 状态: 'todo' }), // 权重 3
    ]
    const sorted = sortKanbanCards(rows, fields, {
      urgent_threshold_days: 3, priority_field: '状态',
    })
    expect(sorted.map(r => r.id)).toEqual([2, 1])
  })

  it('created_at 倒序兜底（新的在前）', () => {
    const rows = [
      makeRow({ id: 1, created_at: '2026-01-01T00:00:00' }),
      makeRow({ id: 2, created_at: '2026-05-01T00:00:00' }),
    ]
    const sorted = sortKanbanCards(rows, fields, { urgent_threshold_days: 3 })
    expect(sorted.map(r => r.id)).toEqual([2, 1])
  })

  it('无 created_at 时按 id 倒序兜底', () => {
    const rows = [
      { id: 1 } as RowResponse,
      { id: 5 } as RowResponse,
    ]
    const sorted = sortKanbanCards(rows, fields, { urgent_threshold_days: 3 })
    expect(sorted.map(r => r.id)).toEqual([5, 1])
  })
})

// ── resolveGroupField ─────────────────────────────────

describe('resolveGroupField', () => {
  it('优先使用 view_options.group_field', () => {
    const { name, def } = resolveGroupField(fields, { group_field: '分数' })
    expect(name).toBe('分数')
    expect(def).toBe(scoreField)
  })

  it('无配置时自动取首个 select/multi_select/link 字段', () => {
    const { name, def } = resolveGroupField([scoreField, statusField], {})
    expect(name).toBe('状态')
    expect(def).toBe(statusField)
  })

  it('没有任何可分组字段时返回 undefined', () => {
    const { name, def } = resolveGroupField([scoreField], {})
    expect(name).toBeUndefined()
    expect(def).toBeUndefined()
  })
})

// ── groupKanbanColumns ────────────────────────────────

describe('groupKanbanColumns', () => {
  const baseOpts = { urgent_threshold_days: 3 }

  it('无分组字段时聚合为单列「全部」', () => {
    const rows = [makeRow({ id: 1 }), makeRow({ id: 2 })]
    const cols = groupKanbanColumns(rows, fields, baseOpts, undefined, undefined)
    expect(cols).toHaveLength(1)
    expect(cols[0].key).toBe('all')
    expect(cols[0].title).toBe('全部')
    expect(cols[0].rows).toHaveLength(2)
  })

  it('select 分组：值转换为 label 列名，空值归「未分组」', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'todo' }),
      makeRow({ id: 2, 状态: 'todo' }),
      makeRow({ id: 3, 状态: 'doing' }),
      makeRow({ id: 4, 状态: null }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '状态', statusField)
    expect(cols.map(c => c.title)).toEqual(['待办', '进行中', '未分组'])
    // 无排序配置时列内走 id 倒序兜底
    expect(cols[0].rows.map(r => r.id)).toEqual([2, 1])
  })

  it('multi_select 分组：数组值取首值（不做 label 映射）作为列名', () => {
    const rows = [
      makeRow({ id: 1, 标签: ['fe', 'be'] }),
      makeRow({ id: 2, 标签: ['be'] }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '标签', tagsField)
    expect(cols.map(c => c.title)).toEqual(['fe', 'be'])
  })

  it('link 分组：取首关联标签作为列名', () => {
    const rows = [
      makeRow({ id: 1, 所属: [{ id: 1, label: '前端组' }] }),
      makeRow({ id: 2, 所属: [{ id: 2, label: '后端组' }] }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '所属', linkField)
    expect(cols.map(c => c.title)).toEqual(['前端组', '后端组'])
  })

  it('未知字段类型（无字段定义）时按原始值/对象兜底分列', () => {
    const rows = [
      makeRow({ id: 1, 其它: { value: '甲' } }),
      makeRow({ id: 2, 其它: [{ value: '乙' }] }),
      makeRow({ id: 3, 其它: '丙' }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '其它', undefined)
    expect(cols.map(c => c.title)).toEqual(['甲', '乙', '丙'])
  })

  it('每列内应用紧急置顶排序', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'todo', 截止: dateStr(30) }), // 正常
      makeRow({ id: 2, 状态: 'todo', 截止: dateStr(-1) }), // 逾期
      makeRow({ id: 3, 状态: 'doing', 截止: dateStr(30) }),
    ]
    const cols = groupKanbanColumns(rows, fields, {
      urgent_threshold_days: 3, due_date_field: '截止', pin_urgent: true,
    }, '状态', statusField)
    expect(cols[0].rows.map(r => r.id)).toEqual([2, 1]) // 逾期置顶
  })

  it('urgentCount 统计逾期 + 阈值内卡片数', () => {
    const rows = [
      makeRow({ id: 1, 截止: dateStr(-1) }), // 逾期
      makeRow({ id: 2, 截止: dateStr(2) }), // 紧急
      makeRow({ id: 3, 截止: dateStr(30) }), // 正常
      makeRow({ id: 4 }), // 无截止值
    ]
    const cols = groupKanbanColumns(rows, fields, {
      urgent_threshold_days: 3, due_date_field: '截止', pin_urgent: true,
    }, undefined, undefined)
    expect(cols[0].urgentCount).toBe(2)
  })

  it('未配置截止字段时 urgentCount 恒为 0', () => {
    const rows = [makeRow({ id: 1 })]
    const cols = groupKanbanColumns(rows, fields, baseOpts, undefined, undefined)
    expect(cols[0].urgentCount).toBe(0)
  })
})

// ── rawValue（新增卡片预填分组值，与 groupKeyForRow 分支对齐）──

describe('groupKanbanColumns rawValue', () => {
  const baseOpts = { urgent_threshold_days: 3 }

  it('select 分组：rawValue 为原始值（供新增卡片预填）', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'todo' }),
      makeRow({ id: 2, 状态: 'doing' }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '状态', statusField)
    expect(cols.map(c => c.rawValue)).toEqual(['todo', 'doing'])
  })

  it('multi_select 分组：rawValue 取数组首值', () => {
    const rows = [
      makeRow({ id: 1, 标签: ['fe', 'be'] }),
      makeRow({ id: 2, 标签: 'solo' }), // 非数组值原样保留
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '标签', tagsField)
    expect(cols.map(c => c.rawValue)).toEqual(['fe', 'solo'])
  })

  it('link 分组：rawValue 取数组首元素（对象或 id）', () => {
    const rows = [
      makeRow({ id: 1, 所属: [{ id: 1, label: '前端组' }] }),
      makeRow({ id: 2, 所属: [42] }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '所属', linkField)
    expect(cols[0]!.rawValue).toEqual({ id: 1, label: '前端组' })
    expect(cols[1]!.rawValue).toBe(42)
  })

  it('无字段定义：rawValue 为原始值', () => {
    const rows = [makeRow({ id: 1, 其它: '丙' })]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '其它', undefined)
    expect(cols[0]!.rawValue).toBe('丙')
  })

  it('空值归「未分组」列：rawValue 为 undefined', () => {
    const rows = [
      makeRow({ id: 1, 状态: null }),
      makeRow({ id: 2, 状态: '' }),
      makeRow({ id: 3 }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '状态', statusField)
    expect(cols).toHaveLength(1)
    expect(cols[0]!.title).toBe('未分组')
    expect(cols[0]!.rawValue).toBeUndefined()
  })

  it('无分组字段：单列 rawValue 无意义（undefined）', () => {
    const rows = [makeRow({ id: 1, 状态: 'todo' })]
    const cols = groupKanbanColumns(rows, fields, baseOpts, undefined, undefined)
    expect(cols[0]!.rawValue).toBeUndefined()
  })

  it('同列多行：rawValue 取首行分组值', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'todo' }),
      makeRow({ id: 2, 状态: 'todo' }),
    ]
    const cols = groupKanbanColumns(rows, fields, baseOpts, '状态', statusField)
    expect(cols).toHaveLength(1)
    expect(cols[0]!.rawValue).toBe('todo')
  })
})

// ── 完成标志判定（resolveDoneCtx / isDoneRow） ────────

describe('resolveDoneCtx', () => {
  it('未配置 / 缺值时返回 null', () => {
    expect(resolveDoneCtx({}, fields)).toBeNull()
    expect(resolveDoneCtx({ done_field: '状态' }, fields)).toBeNull()
    expect(resolveDoneCtx({ done_field: '状态', done_value: '' }, fields)).toBeNull()
    expect(resolveDoneCtx({ done_field: '状态', done_value: undefined }, fields)).toBeNull()
  })

  it('配置完整时返回 ctx 并解析字段定义', () => {
    const ctx = resolveDoneCtx({ done_field: '状态', done_value: 'done' }, fields)
    expect(ctx).not.toBeNull()
    expect(ctx!.field).toBe('状态')
    expect(ctx!.value).toBe('done')
    expect(ctx!.fieldDef).toBe(statusField)
  })

  it('done_value=false 是布尔字段的合法配置值，不视为未配置', () => {
    const ctx = resolveDoneCtx({ done_field: '完成', done_value: false }, fields)
    expect(ctx).not.toBeNull()
    expect(ctx!.value).toBe(false)
  })
})

describe('isDoneRow', () => {
  const boolField = makeField({ id: 6, name: '完成', field_type: 'boolean' })
  const doneFields: Field[] = [...fields, boolField]

  it('未配置时恒为 false', () => {
    expect(isDoneRow(makeRow({ id: 1, 状态: 'done' }), null)).toBe(false)
  })

  it('boolean 字段：严格相等（false 是合法匹配值）', () => {
    const ctxTrue = resolveDoneCtx({ done_field: '完成', done_value: true }, doneFields)!
    const ctxFalse = resolveDoneCtx({ done_field: '完成', done_value: false }, doneFields)!
    expect(isDoneRow(makeRow({ id: 1, 完成: true }), ctxTrue)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 完成: true }), ctxFalse)).toBe(false)
    expect(isDoneRow(makeRow({ id: 1, 完成: false }), ctxFalse)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 完成: null }), ctxFalse)).toBe(false)
  })

  it('select 字段：value 与 label 均可匹配', () => {
    const ctxValue = resolveDoneCtx({ done_field: '状态', done_value: 'done' }, fields)!
    const ctxLabel = resolveDoneCtx({ done_field: '状态', done_value: '已完成' }, fields)!
    expect(isDoneRow(makeRow({ id: 1, 状态: 'done' }), ctxValue)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 状态: 'done' }), ctxLabel)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 状态: 'todo' }), ctxValue)).toBe(false)
    expect(isDoneRow(makeRow({ id: 1, 状态: null }), ctxValue)).toBe(false)
  })

  it('multiselect 字段：数组值任一交集（value/label 归一）', () => {
    const ctxValue = resolveDoneCtx({ done_field: '标签', done_value: ['fe'] }, fields)!
    const ctxLabel = resolveDoneCtx({ done_field: '标签', done_value: ['后端'] }, fields)!
    expect(isDoneRow(makeRow({ id: 1, 标签: ['fe', 'ux'] }), ctxValue)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 标签: 'fe, ux' }), ctxValue)).toBe(true) // 逗号串兼容
    expect(isDoneRow(makeRow({ id: 1, 标签: ['be'] }), ctxLabel)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 标签: ['ux'] }), ctxValue)).toBe(false)
    expect(isDoneRow(makeRow({ id: 1, 标签: null }), ctxValue)).toBe(false)
  })

  it('text 字段：去首尾空格后精确相等', () => {
    const ctx = resolveDoneCtx({ done_field: '名称', done_value: '已完成' }, fields)!
    expect(isDoneRow(makeRow({ id: 1, 名称: '已完成' }), ctx)).toBe(true)
    expect(isDoneRow(makeRow({ id: 1, 名称: ' 已完成 ' }), ctx)).toBe(true)
    // 包含关系不算匹配（「未完成」≠「已完成」）
    expect(isDoneRow(makeRow({ id: 1, 名称: '未完成' }), ctx)).toBe(false)
    expect(isDoneRow(makeRow({ id: 1, 名称: null }), ctx)).toBe(false)
  })
})

// ── 完成勾选切换值（buildDoneToggleValue） ─────────────

describe('buildDoneToggleValue', () => {
  const boolField = makeField({ id: 6, name: '完成', field_type: 'boolean' })
  const doneFields: Field[] = [...fields, boolField]

  it('select 未完成 → 勾选写入 done_value', () => {
    const ctx = resolveDoneCtx({ done_field: '状态', done_value: 'done' }, fields)!
    expect(buildDoneToggleValue(makeRow({ id: 1, 状态: 'todo' }), ctx)).toBe('done')
  })

  it('select 已完成 → 取消清空（null）', () => {
    const ctx = resolveDoneCtx({ done_field: '状态', done_value: 'done' }, fields)!
    expect(buildDoneToggleValue(makeRow({ id: 1, 状态: 'done' }), ctx)).toBeNull()
  })

  it('text 未完成 → 勾选写入匹配文本；已完成 → 取消清空', () => {
    const ctx = resolveDoneCtx({ done_field: '名称', done_value: '已完成' }, fields)!
    expect(buildDoneToggleValue(makeRow({ id: 1, 名称: '待办' }), ctx)).toBe('已完成')
    expect(buildDoneToggleValue(makeRow({ id: 1, 名称: '已完成' }), ctx)).toBeNull()
  })

  it('boolean done_value=true：勾选写 true，取消写 false', () => {
    const ctx = resolveDoneCtx({ done_field: '完成', done_value: true }, doneFields)!
    expect(buildDoneToggleValue(makeRow({ id: 1, 完成: false }), ctx)).toBe(true)
    expect(buildDoneToggleValue(makeRow({ id: 1, 完成: true }), ctx)).toBe(false)
  })

  it('boolean done_value=false（false 即完成）：勾选写 false，取消写 true', () => {
    const ctx = resolveDoneCtx({ done_field: '完成', done_value: false }, doneFields)!
    expect(buildDoneToggleValue(makeRow({ id: 1, 完成: true }), ctx)).toBe(false)
    expect(buildDoneToggleValue(makeRow({ id: 1, 完成: false }), ctx)).toBe(true)
  })

  it('multiselect：勾选写入匹配数组，取消移除匹配项（移空则清空）', () => {
    const ctx = resolveDoneCtx({ done_field: '标签', done_value: ['fe'] }, fields)!
    expect(buildDoneToggleValue(makeRow({ id: 1, 标签: ['be'] }), ctx)).toEqual(['fe'])
    expect(buildDoneToggleValue(makeRow({ id: 1, 标签: ['fe', 'be'] }), ctx)).toEqual(['be'])
    expect(buildDoneToggleValue(makeRow({ id: 1, 标签: ['fe'] }), ctx)).toBeNull()
  })
})

describe('完成标志与紧急置顶/计数的交互', () => {
  const doneOpts = {
    urgent_threshold_days: 3, due_date_field: '截止', pin_urgent: true,
    done_field: '状态', done_value: 'done',
  }

  it('sortKanbanCards：完成卡片即使逾期也不参与紧急置顶', () => {
    const rows = [
      makeRow({ id: 1, created_at: '2026-01-01T00:00:00', 状态: 'done', 截止: dateStr(-5) }), // 完成且逾期
      makeRow({ id: 2, created_at: '2026-01-01T00:00:00', 状态: 'todo', 截止: dateStr(-5) }), // 逾期
    ]
    const sorted = sortKanbanCards(rows, fields, doneOpts)
    // 两者 created_at 相同 → 走 id 倒序兜底；若完成卡仍参与置顶则会是 [1, 2]
    expect(sorted.map(r => r.id)).toEqual([2, 1])
  })

  it('groupKanbanColumns：完成卡片不计入列头 urgentCount', () => {
    const rows = [
      makeRow({ id: 1, 状态: 'done', 截止: dateStr(-5) }), // 完成 + 逾期 → 不计
      makeRow({ id: 2, 状态: 'todo', 截止: dateStr(-5) }), // 逾期 → 计
      makeRow({ id: 3, 状态: 'todo', 截止: dateStr(2) }), // 紧急 → 计
      makeRow({ id: 4, 状态: 'todo' }), // 无截止 → 不计
    ]
    const cols = groupKanbanColumns(rows, fields, doneOpts, undefined, undefined)
    expect(cols[0]!.urgentCount).toBe(2)
  })
})

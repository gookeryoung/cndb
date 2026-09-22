/** fieldOps 单元测试 —— 操作符映射、别名解析、select options 提取 */
import { describe, expect, it } from 'vitest'
import {
  DONE_FLAG_OPS,
  extractSelectOptions,
  FIELD_TYPE_ALIASES,
  getOpsForField,
  matchValueCondition,
} from './fieldOps'

describe('getOpsForField 按字段类型返回操作符组', () => {
  it('text 类型返回文本操作符（含包含/等于/为空）', () => {
    const ops = getOpsForField('text')
    expect(ops.map((o) => o.op)).toEqual([
      'contains', 'starts_with', 'ends_with', '=', '!=', 'is_empty', 'is_not_empty',
    ])
  })

  it('number 类型含比较操作符且值编辑器为 number', () => {
    const ops = getOpsForField('number')
    const gt = ops.find((o) => o.op === '>')
    expect(gt).toMatchObject({ label: '大于', valueKind: 'number' })
    expect(ops.find((o) => o.op === 'is_empty')?.needValue).toBe(true)
  })

  it('select 类型操作符值编辑器为 select', () => {
    const ops = getOpsForField('select')
    expect(ops.find((o) => o.op === '=')?.valueKind).toBe('select')
    expect(ops.find((o) => o.op === 'in')?.valueKind).toBe('select')
  })

  it('date 类型操作符值编辑器为 date', () => {
    const ops = getOpsForField('date')
    expect(ops.find((o) => o.op === '>')?.valueKind).toBe('date')
    expect(ops.find((o) => o.op === '>')?.label).toBe('晚于')
  })

  it('link 类型含关联专属操作符', () => {
    const ops = getOpsForField('link')
    expect(ops.map((o) => o.op)).toContain('has_any')
    expect(ops.map((o) => o.op)).toContain('has_all')
  })

  it('未知类型兜底返回 text 操作符组', () => {
    expect(getOpsForField('nonexistent_type')).toEqual(getOpsForField('text'))
  })
})

describe('getOpsForField 别名解析', () => {
  it.each([
    ['long_text', 'longtext'],
    ['decimal', 'float'],
    ['multi_select', 'multiselect'],
    ['rich_text', 'longtext'],
    ['link_to_table', 'link'],
  ])('别名 %s 解析为 %s 的操作符组', (alias, canonical) => {
    expect(getOpsForField(alias)).toEqual(getOpsForField(canonical))
  })

  it('别名映射表覆盖五个历史类型名', () => {
    expect(Object.keys(FIELD_TYPE_ALIASES)).toEqual([
      'long_text', 'decimal', 'multi_select', 'rich_text', 'link_to_table',
    ])
  })
})

describe('extractSelectOptions 双历史格式兼容', () => {
  it('string[] 旧格式转为 value/label 同值', () => {
    expect(extractSelectOptions({ options: ['active', 'done'] })).toEqual([
      { value: 'active', label: 'active' },
      { value: 'done', label: 'done' },
    ])
  })

  it('对象数组新格式保留 color 字段', () => {
    const config = {
      options: [
        { label: '进行中', value: 'active', color: 'blue' },
        { label: '完成', value: 'done', color: 'green' },
      ],
    }
    expect(extractSelectOptions(config)).toEqual([
      { value: 'active', label: '进行中', color: 'blue' },
      { value: 'done', label: '完成', color: 'green' },
    ])
  })

  it('对象缺少 label 时回退 value/name', () => {
    expect(extractSelectOptions({ options: [{ value: 'v1' }] })).toEqual([
      { value: 'v1', label: 'v1' },
    ])
    expect(extractSelectOptions({ options: [{ name: 'n1' }] })).toEqual([
      { value: 'n1', label: 'n1' },
    ])
  })

  it('空 config / 非 object / 空 options / 缺 options 均返回空数组', () => {
    expect(extractSelectOptions(undefined)).toEqual([])
    expect(extractSelectOptions(null)).toEqual([])
    expect(extractSelectOptions('not-object')).toEqual([])
    expect(extractSelectOptions({})).toEqual([])
    expect(extractSelectOptions({ options: [] })).toEqual([])
  })

  it('对象数组格式过滤掉 value 与 label 均为空的项', () => {
    expect(extractSelectOptions({ options: [{ value: '', label: '' }, { value: 'ok' }] })).toEqual([
      { value: 'ok', label: 'ok' },
    ])
  })

  it('混合数组按首元素类型走分支（首元素为 string 时整组按字符串处理）', () => {
    const result = extractSelectOptions({ options: ['', { value: 'x' }, 'ok'] })
    expect(result[0]).toEqual({ value: '', label: '' })
    expect(result[2]).toEqual({ value: 'ok', label: 'ok' })
  })
})

describe('DONE_FLAG_OPS 完成标志允许的操作符子集', () => {
  it('仅包含等值与无值判定，且逐项存在于筛选操作符表', () => {
    expect(DONE_FLAG_OPS).toEqual(['=', 'is_empty', 'is_not_empty'])
    const allGroups = Object.values(
      Object.fromEntries(['text', 'select', 'multiselect', 'date', 'boolean'].map((t) => [t, getOpsForField(t)])),
    )
    for (const op of DONE_FLAG_OPS) {
      expect(allGroups.some((group) => group.some((o) => o.op === op))).toBe(true)
    }
  })
})

describe('matchValueCondition 按字段类型 × 操作符判定行值', () => {
  const selectField = {
    field_type: 'select',
    config: { options: [{ label: '完成', value: 'done', color: 'green' }] },
  } as never
  const multiField = {
    field_type: 'multiselect',
    config: { options: [{ label: '标签A', value: 'a' }, { label: '标签B', value: 'b' }] },
  } as never

  // text × 等值：去首尾空格后精确相等
  it.each([
    ['已完成', '已完成', true],
    [' 已完成 ', '已完成', true],
    ['进行中', '已完成', false],
    [null, '已完成', false],
    [undefined, '', false],
  ])('text 等值：raw=%j value=%j → %j', (raw, value, expected) => {
    expect(matchValueCondition(raw, '=', value, { field_type: 'text' } as never)).toBe(expected)
  })

  // date × 等值：与 text 同口径（字符串精确比较）
  it('date 等值按字符串精确比较', () => {
    const def = { field_type: 'date' } as never
    expect(matchValueCondition('2026-01-01', '=', '2026-01-01', def)).toBe(true)
    expect(matchValueCondition('2026-01-01', '=', '2026-01-02', def)).toBe(false)
    expect(matchValueCondition(null, '=', '2026-01-02', def)).toBe(false)
  })

  // boolean × 等值：严格相等，false 是合法匹配值
  it('boolean 等值严格相等且 false 合法', () => {
    const def = { field_type: 'boolean' } as never
    expect(matchValueCondition(true, '=', true, def)).toBe(true)
    expect(matchValueCondition(false, '=', false, def)).toBe(true)
    expect(matchValueCondition(false, '=', true, def)).toBe(false)
    expect(matchValueCondition(null, '=', false, def)).toBe(false)
  })

  // select × 等值：命中 option 时比较 value/label；未命中时比较原值
  it.each([
    ['done', 'done', true],
    ['完成', 'done', true],
    ['done', '完成', true],
    ['未知值', '未知值', true],
    ['未知值', 'done', false],
    [null, 'done', false],
  ])('select 等值：raw=%j value=%j → %j', (raw, value, expected) => {
    expect(matchValueCondition(raw, '=', value, selectField)).toBe(expected)
  })

  // multiselect × 等值：行值与配置值归一为 option value 后求交集
  it.each([
    [['a'], 'a', true],
    [['a', 'b'], 'b', true],
    [['标签A'], 'a', true],
    [['a'], '标签A', true],
    [['c'], 'a', false],
    [[], 'a', false],
    [null, 'a', false],
  ])('multiselect 等值：raw=%j value=%j → %j', (raw, value, expected) => {
    expect(matchValueCondition(raw, '=', value, multiField)).toBe(expected)
  })

  // is_empty / is_not_empty：无值直通，口径为 null/undefined/''（数组为空）
  it.each([
    [null, true],
    [undefined, true],
    ['', true],
    [' ', false],
    ['x', false],
    [[], true],
    [['a'], false],
  ])('is_empty：raw=%j → %j', (raw, expected) => {
    expect(matchValueCondition(raw, 'is_empty', undefined, { field_type: 'text' } as never)).toBe(expected)
    expect(matchValueCondition(raw, 'is_empty', undefined, multiField)).toBe(expected)
  })

  it.each([
    [null, false],
    ['', false],
    [' ', true],
    ['x', true],
    [[], false],
    [['a'], true],
  ])('is_not_empty：raw=%j → %j', (raw, expected) => {
    expect(matchValueCondition(raw, 'is_not_empty', undefined, { field_type: 'text' } as never)).toBe(expected)
    expect(matchValueCondition(raw, 'is_not_empty', undefined, selectField)).toBe(expected)
  })

  it('text + is_not_empty 不需要 value 也能判定（完成标志"非空即完成"场景）', () => {
    expect(matchValueCondition('任意文本', 'is_not_empty', undefined, { field_type: 'text' } as never)).toBe(true)
    expect(matchValueCondition(null, 'is_not_empty', undefined, { field_type: 'date' } as never)).toBe(false)
  })

  it('未知操作符保守返回 false', () => {
    expect(matchValueCondition('x', 'contains', 'x', { field_type: 'text' } as never)).toBe(false)
  })
})

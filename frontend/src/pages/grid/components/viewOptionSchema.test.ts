/** viewOptionSchema 单元测试 —— schema 解析、字段匹配、默认值回退、自动推断 */
import { describe, expect, it } from 'vitest'
import {
  _fieldMatchesSchema,
  findOptionSchema,
  getOptionSchema,
  resolveAutoField,
  resolveFieldOptions,
  resolveOpts,
} from './viewOptionSchema'
import { makeField } from '@/test/fixtures'

describe('getOptionSchema 五种视图 + 未知类型', () => {
  it('kanban 返回 11 项 schema', () => {
    expect(getOptionSchema('kanban')).toHaveLength(11)
    expect(getOptionSchema('kanban').map((o) => o.key)).toContain('group_field')
  })

  it('calendar 返回 4 项，start_field 必填', () => {
    const schema = getOptionSchema('calendar')
    expect(schema).toHaveLength(4)
    expect(schema.find((o) => o.key === 'start_field')?.required).toBe(true)
  })

  it('gallery 返回 5 项', () => {
    expect(getOptionSchema('gallery')).toHaveLength(5)
  })

  it('gantt 返回 9 项，start/end date 必填', () => {
    const schema = getOptionSchema('gantt')
    expect(schema).toHaveLength(9)
    expect(schema.find((o) => o.key === 'start_date_field')?.required).toBe(true)
    expect(schema.find((o) => o.key === 'end_date_field')?.required).toBe(true)
  })

  it('wbs 返回 9 项，parent_field 必填', () => {
    const schema = getOptionSchema('wbs')
    expect(schema).toHaveLength(9)
    expect(schema.find((o) => o.key === 'parent_field')?.required).toBe(true)
  })

  it('未知视图类型返回空数组', () => {
    expect(getOptionSchema('unknown_type')).toEqual([])
  })

  it('findOptionSchema 按 viewType+key 查找，找不到返回 undefined', () => {
    expect(findOptionSchema('kanban', 'group_field')?.label).toBe('分组字段')
    expect(findOptionSchema('kanban', 'nope')).toBeUndefined()
    expect(findOptionSchema('unknown', 'group_field')).toBeUndefined()
  })
})

describe('_fieldMatchesSchema 字段类型匹配', () => {
  const textField = makeField({ id: 1, name: 't', field_type: 'text' })
  const longTextField = makeField({ id: 2, name: 'lt', field_type: 'long_text' })
  const primaryField = makeField({ id: 3, name: 'id', field_type: 'text', is_primary: true })
  const hiddenField = makeField({ id: 4, name: 'h', field_type: 'text', hidden: true })

  it('fieldTypes 未定义时全匹配', () => {
    expect(_fieldMatchesSchema(textField, undefined)).toBe(true)
  })

  it('__all__ 通配符排除 hidden 字段', () => {
    expect(_fieldMatchesSchema(textField, ['__all__'])).toBe(true)
    expect(_fieldMatchesSchema(hiddenField, ['__all__'])).toBe(false)
  })

  it('原始类型名与别名均可匹配：字段的别名类型解析为规范名后匹配 schema', () => {
    // 字段类型为历史别名 long_text，schema 用规范名 longtext → 匹配
    expect(_fieldMatchesSchema(longTextField, ['longtext'])).toBe(true)
    // 字段类型已是规范名 longtext，schema 直接列规范名 → 匹配
    expect(_fieldMatchesSchema(makeField({ id: 5, name: 'lt2', field_type: 'longtext' }), ['longtext'])).toBe(true)
    // schema 列历史别名 long_text 而字段是规范名 → 不匹配（schema 应使用规范名）
    expect(_fieldMatchesSchema(makeField({ id: 6, name: 'lt3', field_type: 'longtext' }), ['long_text'])).toBe(false)
  })

  it('is_primary 作为特殊类型匹配主键字段', () => {
    expect(_fieldMatchesSchema(primaryField, ['is_primary'])).toBe(true)
    expect(_fieldMatchesSchema(textField, ['is_primary'])).toBe(false)
  })

  it('不匹配的类型返回 false', () => {
    expect(_fieldMatchesSchema(textField, ['select', 'date'])).toBe(false)
  })
})

describe('resolveFieldOptions 生成下拉选项', () => {
  it('按 fieldTypes 过滤并生成 value/label（label 含类型后缀）', () => {
    const fields = [
      makeField({ id: 1, name: 'status', field_type: 'select' }),
      makeField({ id: 2, name: 'title', field_type: 'text' }),
    ]
    const schema = findOptionSchema('kanban', 'group_field')!
    expect(resolveFieldOptions(fields, schema)).toEqual([
      { value: 'status', label: 'status (select)' },
    ])
  })
})

describe('resolveOpts 默认值回退', () => {
  const schema = getOptionSchema('kanban')

  it('undefined / null 原始配置回退 defaultValue（card_sort_direction=desc、urgent_threshold_days=3）', () => {
    for (const raw of [undefined, null]) {
      const out = resolveOpts(raw, schema)
      expect(out.card_sort_direction).toBe('desc')
      expect(out.urgent_threshold_days).toBe(3)
      expect(out.pin_urgent).toBe(true)
    }
  })

  it('switch 的 false 是有效值，不回退 defaultValue（expand_all=false 场景，用 wbs 验证）', () => {
    const wbsSchema = getOptionSchema('wbs')
    const out = resolveOpts({ expand_all: false }, wbsSchema)
    expect(out.expand_all).toBe(false)
  })

  it('显式配置覆盖 defaultValue', () => {
    const out = resolveOpts({ card_sort_direction: 'asc' }, schema)
    expect(out.card_sort_direction).toBe('asc')
  })

  it('无 defaultValue 的 key 不产生额外条目', () => {
    const out = resolveOpts({}, schema)
    expect('group_field' in out).toBe(false)
    expect('title_field' in out).toBe(false)
  })

  it('schema 外字段原样保留（向后兼容）', () => {
    const out = resolveOpts({ group_field: 's', legacy_key: 'x' }, schema)
    expect(out.legacy_key).toBe('x')
    expect(out.group_field).toBe('s')
  })
})

describe('resolveAutoField 自动推断', () => {
  const fields = [
    makeField({ id: 1, name: 'status', field_type: 'select' }),
    makeField({ id: 2, name: 'title', field_type: 'text' }),
    makeField({ id: 3, name: 'id', field_type: 'number', is_primary: true }),
    makeField({ id: 4, name: 'desc', field_type: 'long_text' }),
  ]

  it('按 fieldTypes 顺序取第一个匹配类型', () => {
    // kanban title_field: ['text', 'longtext'] → 先匹配 text 的 title
    expect(resolveAutoField(fields, findOptionSchema('kanban', 'title_field'))).toBe('title')
    // kanban group_field: ['select', ...] → status
    expect(resolveAutoField(fields, findOptionSchema('kanban', 'group_field'))).toBe('status')
  })

  it('按类型找不到时 includePrimary 回退主键字段', () => {
    const onlyPrimary = [makeField({ id: 3, name: 'id', field_type: 'number', is_primary: true })]
    expect(resolveAutoField(onlyPrimary, findOptionSchema('kanban', 'title_field'))).toBe('id')
  })

  it('includePrimary 也没有时回退 literalFallback', () => {
    expect(resolveAutoField([], findOptionSchema('kanban', 'title_field'))).toBe('id')
  })

  it('schema 未定义时返回 undefined', () => {
    expect(resolveAutoField(fields, undefined)).toBeUndefined()
  })

  it('schema 无 fieldTypes/includePrimary/literalFallback 时返回 undefined', () => {
    const bareSchema = { key: 'x', label: 'x', kind: 'field_select' as const }
    expect(resolveAutoField(fields, bareSchema)).toBeUndefined()
  })
})

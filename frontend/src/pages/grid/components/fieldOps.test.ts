/** fieldOps 单元测试 —— 操作符映射、别名解析、select options 提取 */
import { describe, expect, it } from 'vitest'
import {
  extractSelectOptions,
  FIELD_TYPE_ALIASES,
  getOpsForField,
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

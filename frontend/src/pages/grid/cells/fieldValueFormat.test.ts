/** fieldValueFormat 单元测试 —— 各字段类型值的展示格式化 */
import { describe, expect, it } from 'vitest'
import {
  buildLinkRowLabel,
  extractImageUrl,
  formatFieldDisplayValue,
  formatLinkValue,
  formatMultiSelectValue,
  getLinkFirstLabel,
  getMultiSelectFirstLabel,
  getSelectLabel,
  pickLinkLabelFieldName,
} from './fieldValueFormat'
import { makeField } from '@/test/fixtures'

describe('formatLinkValue', () => {
  it('对象数组展平为 value 字符串数组', () => {
    expect(formatLinkValue([{ id: 1, value: '张三' }, { id: 2, value: '李四' }])).toEqual([
      '张三', '李四',
    ])
  })

  it('对象缺少 value 时回退 label / id', () => {
    expect(formatLinkValue([{ id: 7, label: 'lab' }])).toEqual(['lab'])
    expect(formatLinkValue([{ id: 7 }])).toEqual(['7'])
  })

  it('单对象返回单元素数组', () => {
    expect(formatLinkValue({ id: 1, value: 'a' })).toEqual(['a'])
  })

  it('裸值（字符串/数字）直接包装为数组', () => {
    expect(formatLinkValue('plain')).toEqual(['plain'])
    expect(formatLinkValue(42)).toEqual(['42'])
  })

  it('数组内的裸值转字符串并过滤空串（null 项转为 "null" 保留）', () => {
    expect(formatLinkValue(['a', 1, '', null])).toEqual(['a', '1', 'null'])
  })

  it('空值（null/undefined/空串/空数组）返回空数组', () => {
    expect(formatLinkValue(null)).toEqual([])
    expect(formatLinkValue(undefined)).toEqual([])
    expect(formatLinkValue('')).toEqual([])
    expect(formatLinkValue([])).toEqual([])
  })
})

describe('getLinkFirstLabel', () => {
  it('取第一个 link 的 value；空值返回空串', () => {
    expect(getLinkFirstLabel([{ id: 1, value: '首' }, { id: 2, value: '次' }])).toBe('首')
    expect(getLinkFirstLabel([])).toBe('')
    expect(getLinkFirstLabel(null)).toBe('')
  })
})

describe('pickLinkLabelFieldName（link 下拉标签字段选择）', () => {
  it('优先取 is_primary 的 text 字段', () => {
    const fields = [
      makeField({ id: 1, name: '备注', field_type: 'text', order: 0 }),
      makeField({ id: 2, name: '标题', field_type: 'text', is_primary: true, order: 1 }),
    ]
    expect(pickLinkLabelFieldName(fields)).toBe('标题')
  })

  it('无主字段时取第一个 text 字段', () => {
    const fields = [
      makeField({ id: 1, name: '数量', field_type: 'number', order: 0 }),
      makeField({ id: 2, name: '名称', field_type: 'text', order: 1 }),
    ]
    expect(pickLinkLabelFieldName(fields)).toBe('名称')
  })

  it('longtext 不参与选择（内容过长不适合做标签）', () => {
    const fields = [
      makeField({ id: 1, name: '正文', field_type: 'longtext', order: 0 }),
      makeField({ id: 2, name: '名称', field_type: 'text', order: 1 }),
    ]
    expect(pickLinkLabelFieldName(fields)).toBe('名称')
  })

  it('无 text 字段 / 空列表返回 null', () => {
    expect(pickLinkLabelFieldName([makeField({ id: 1, name: 'n', field_type: 'number' })])).toBeNull()
    expect(pickLinkLabelFieldName([])).toBeNull()
  })

  it('已删除（trashed）的 text 字段不参与选择', () => {
    const fields = [
      makeField({ id: 1, name: '废字段', field_type: 'text', trashed: true, order: 0 }),
      makeField({ id: 2, name: '名称', field_type: 'text', order: 1 }),
    ]
    expect(pickLinkLabelFieldName(fields)).toBe('名称')
  })
})

describe('buildLinkRowLabel（link 下拉选项标签）', () => {
  it('优先取 labelField 对应的业务值', () => {
    expect(buildLinkRowLabel({ id: 1, 姓名: '张三' }, '姓名')).toBe('张三')
  })

  it('labelField 值为空 / 缺失时回退 #id', () => {
    expect(buildLinkRowLabel({ id: 3, 姓名: '' }, '姓名')).toBe('#3')
    expect(buildLinkRowLabel({ id: 3, 姓名: null }, '姓名')).toBe('#3')
    expect(buildLinkRowLabel({ id: 3 }, '姓名')).toBe('#3')
  })

  it('无 labelField 时直接回退 #id', () => {
    expect(buildLinkRowLabel({ id: 5, 姓名: '张三' }, null)).toBe('#5')
    expect(buildLinkRowLabel({ id: 5, 姓名: '张三' }, undefined)).toBe('#5')
  })

  it('值为对象（如 link/attachment 嵌套）时不适合做标签，回退 #id', () => {
    expect(buildLinkRowLabel({ id: 2, 数据: { a: 1 } }, '数据')).toBe('#2')
  })
})

describe('formatMultiSelectValue', () => {
  it('数组逐项转字符串并过滤空项', () => {
    expect(formatMultiSelectValue(['a', 'b', ''])).toEqual(['a', 'b'])
    expect(formatMultiSelectValue([1, 2])).toEqual(['1', '2'])
  })

  it('逗号分隔字符串按逗号拆分并 trim', () => {
    expect(formatMultiSelectValue('a, b ,c')).toEqual(['a', 'b', 'c'])
  })

  it('空值与纯逗号串返回空数组', () => {
    expect(formatMultiSelectValue('')).toEqual([])
    expect(formatMultiSelectValue(null)).toEqual([])
    expect(formatMultiSelectValue(undefined)).toEqual([])
    expect(formatMultiSelectValue(',,,')).toEqual([])
  })
})

describe('getMultiSelectFirstLabel', () => {
  it('取第一个标签；空值返回空串', () => {
    expect(getMultiSelectFirstLabel('a,b')).toBe('a')
    expect(getMultiSelectFirstLabel('')).toBe('')
  })
})

describe('getSelectLabel', () => {
  const selectField = makeField({
    id: 1,
    name: 'status',
    field_type: 'select',
    config: { options: [{ label: '进行中', value: 'active', color: 'blue' }] },
  })

  it('命中 options 时返回 label', () => {
    expect(getSelectLabel(selectField, 'active')).toBe('进行中')
  })

  it('未命中时原样返回值字符串', () => {
    expect(getSelectLabel(selectField, 'unknown')).toBe('unknown')
  })

  it('无 options 时原样返回值字符串', () => {
    const noConfig = makeField({ id: 2, name: 's2', field_type: 'select' })
    expect(getSelectLabel(noConfig, 'raw')).toBe('raw')
  })

  it('空值（null/undefined/空串）返回空串', () => {
    expect(getSelectLabel(selectField, null)).toBe('')
    expect(getSelectLabel(selectField, undefined)).toBe('')
    expect(getSelectLabel(selectField, '')).toBe('')
  })
})

describe('extractImageUrl', () => {
  it('http/https 开头的字符串直接返回', () => {
    expect(extractImageUrl('https://x.com/a.png')).toBe('https://x.com/a.png')
    expect(extractImageUrl('http://x.com/a.png')).toBe('http://x.com/a.png')
  })

  it('以 / 开头的相对路径字符串直接返回', () => {
    expect(extractImageUrl('/media/a.png')).toBe('/media/a.png')
  })

  it('不以 http 或 / 开头的字符串返回 null', () => {
    expect(extractImageUrl('media/a.png')).toBeNull()
    expect(extractImageUrl('')).toBeNull()
  })

  it('单对象取 url 或 value 字段', () => {
    expect(extractImageUrl({ url: 'https://x.com/1.png' })).toBe('https://x.com/1.png')
    expect(extractImageUrl({ value: '/media/2.png' })).toBe('/media/2.png')
  })

  it('对象内 URL 不合法时返回 null', () => {
    expect(extractImageUrl({ url: 'not-a-url' })).toBeNull()
    expect(extractImageUrl({})).toBeNull()
  })

  it('数组取第一个可用 URL', () => {
    expect(extractImageUrl([{ url: 'https://x.com/1.png' }, { url: 'https://x.com/2.png' }])).toBe(
      'https://x.com/1.png',
    )
  })

  it('数字/布尔等非法类型返回 null', () => {
    expect(extractImageUrl(123)).toBeNull()
    expect(extractImageUrl(true)).toBeNull()
  })
})

describe('formatFieldDisplayValue 按字段类型分支', () => {
  it('select 显示 label', () => {
    const f = makeField({
      id: 1,
      name: 'status',
      field_type: 'select',
      config: { options: [{ label: '进行中', value: 'active' }] },
    })
    expect(formatFieldDisplayValue(f, 'active')).toBe('进行中')
  })

  it('multi_select 逗号连接（含 multi_select 别名）', () => {
    for (const ft of ['multi_select', 'multiselect'] as const) {
      const f = makeField({ id: 1, name: 'tags', field_type: ft })
      expect(formatFieldDisplayValue(f, ['a', 'b'])).toBe('a, b')
    }
  })

  it('link 多值逗号连接', () => {
    const f = makeField({ id: 1, name: 'owner', field_type: 'link' })
    expect(formatFieldDisplayValue(f, [{ id: 1, value: '张三' }, { id: 2, value: '李四' }])).toBe(
      '张三, 李四',
    )
  })

  it('boolean 显示 是/否', () => {
    const f = makeField({ id: 1, name: 'done', field_type: 'boolean' })
    expect(formatFieldDisplayValue(f, true)).toBe('是')
    expect(formatFieldDisplayValue(f, false)).toBe('否')
  })

  it('date/datetime/timestamp 与默认分支均 String() 输出', () => {
    for (const ft of ['date', 'datetime', 'timestamp', 'text'] as const) {
      const f = makeField({ id: 1, name: 'v', field_type: ft })
      expect(formatFieldDisplayValue(f, 'raw')).toBe('raw')
    }
  })

  it('空值短路：null/undefined/空串一律返回空串', () => {
    for (const ft of ['select', 'multi_select', 'link', 'boolean', 'text'] as const) {
      const f = makeField({ id: 1, name: 'v', field_type: ft })
      expect(formatFieldDisplayValue(f, null)).toBe('')
      expect(formatFieldDisplayValue(f, undefined)).toBe('')
      expect(formatFieldDisplayValue(f, '')).toBe('')
    }
  })
})

import { describe, expect, it } from 'vitest'
import {
  FIELD_TYPE_META, FIELD_TYPE_OPTIONS, PREVIEW_FIELD_TYPE_VALUES,
  getFieldTypeColor, getFieldTypeLabel,
} from './fieldTypeMeta'

describe('fieldTypeMeta 字段类型元数据', () => {
  it('16 个主类型的标签/类别/颜色符合统一标准', () => {
    const expected: Record<string, [string, string, string]> = {
      text: ['单行文本', '基础', 'blue'],
      longtext: ['多行文本', '基础', 'cyan'],
      boolean: ['是/否', '基础', 'purple'],
      number: ['整数', '数字', 'green'],
      float: ['小数', '数字', 'green'],
      percentage: ['百分比', '数字', 'lime'],
      date: ['日期', '日期', 'orange'],
      datetime: ['日期时间', '日期', 'orange'],
      timestamp: ['时间戳', '日期', 'orange'],
      select: ['单选', '选择', 'gold'],
      multiselect: ['多选', '选择', 'gold'],
      email: ['邮箱', '高级', 'geekblue'],
      url: ['链接', '高级', 'geekblue'],
      phone: ['电话', '高级', 'geekblue'],
      link: ['关联', '关联', 'magenta'],
      attachment: ['附件', '高级', 'volcano'],
    }
    for (const [type, [label, category, color]] of Object.entries(expected)) {
      expect(FIELD_TYPE_META[type], type).toEqual({ label, category, color })
    }
  })

  it('历史别名映射到归一化后的中文标签', () => {
    expect(getFieldTypeLabel('long_text')).toBe('多行文本')
    expect(getFieldTypeLabel('decimal')).toBe('小数')
    expect(getFieldTypeLabel('multi_select')).toBe('多选')
    expect(getFieldTypeLabel('json')).toBe('JSON')
    expect(getFieldTypeLabel('formula')).toBe('公式')
    expect(getFieldTypeLabel('created_time')).toBe('创建时间')
  })

  it('未知类型：标签返回原始值、颜色返回 default', () => {
    expect(getFieldTypeLabel('__unknown__')).toBe('__unknown__')
    expect(getFieldTypeColor('__unknown__')).toBe('default')
  })

  it('所有元数据颜色均为 antd 预设色名或 default（非 HEX）', () => {
    for (const meta of Object.values(FIELD_TYPE_META)) {
      expect(meta.color).toMatch(/^(default|[a-z]+(-inverse)?)$/)
    }
  })

  it('FIELD_TYPE_OPTIONS 恰含 16 个主类型且不含别名/系统类型', () => {
    expect(FIELD_TYPE_OPTIONS).toHaveLength(16)
    const values = FIELD_TYPE_OPTIONS.map(o => o.value)
    expect(values).toContain('text')
    expect(values).not.toContain('long_text')
    expect(values).not.toContain('formula')
    // 每项都带类别
    for (const o of FIELD_TYPE_OPTIONS) {
      expect(o.category).toBeTruthy()
      expect(o.label).not.toMatch(/[a-z]/) // 纯中文标签
    }
  })

  it('PREVIEW_FIELD_TYPE_VALUES 恰为导入预览可切换的 12 项子集', () => {
    expect(PREVIEW_FIELD_TYPE_VALUES).toEqual([
      'text', 'number', 'float', 'boolean', 'date', 'datetime',
      'select', 'multiselect', 'email', 'url', 'phone', 'percentage',
    ])
    expect(PREVIEW_FIELD_TYPE_VALUES).not.toContain('link')
    expect(PREVIEW_FIELD_TYPE_VALUES).not.toContain('attachment')
    // 子集内每项在元数据表中均可查
    for (const v of PREVIEW_FIELD_TYPE_VALUES) {
      expect(FIELD_TYPE_META[v]).toBeDefined()
    }
  })
})

import { describe, expect, it } from 'vitest'

import { autoIncrementHint, formatIncrementExample, isAutoIncrementField } from './fieldIncrement'

describe('isAutoIncrementField', () => {
  it('仅单行文本 + default_mode=auto_increment 判定为自动编号', () => {
    expect(isAutoIncrementField({ field_type: 'text', config: { default_mode: 'auto_increment' } })).toBe(true)
    expect(isAutoIncrementField({ field_type: 'text', config: {} })).toBe(false)
    expect(isAutoIncrementField({ field_type: 'long_text', config: { default_mode: 'auto_increment' } })).toBe(false)
  })
})

describe('formatIncrementExample', () => {
  it('按前缀 / 补零位数 / 起始编号拼出示例', () => {
    expect(formatIncrementExample({ increment_prefix: 'PRJ-', increment_padding: 4, increment_start: 1 })).toBe('PRJ-0001')
    expect(formatIncrementExample({ increment_prefix: 'WO-', increment_padding: 2, increment_start: 7 })).toBe('WO-07')
  })

  it('缺省配置回退为 0001，越界值收敛到合法区间', () => {
    expect(formatIncrementExample(undefined)).toBe('0001')
    expect(formatIncrementExample({ increment_padding: 99 })).toBe('0000000001')
    expect(formatIncrementExample({ increment_start: -3 })).toBe('0000')
  })
})

describe('autoIncrementHint', () => {
  it('提示文案包含示例编号', () => {
    expect(
      autoIncrementHint({ field_type: 'text', config: { default_mode: 'auto_increment', increment_prefix: 'PRJ-' } }),
    ).toBe('保存时自动生成（如 PRJ-0001）')
  })
})

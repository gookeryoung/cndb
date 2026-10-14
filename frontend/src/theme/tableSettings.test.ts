/**
 * tableSettings 纯逻辑单元测试 —— density → antd size 映射.
 *
 * localStorage 读写与字段合并的职责已收敛到 @/store/tableSettings（zustand persist），
 * 本文件不再覆盖第二套读写实现。
 */

import { describe, expect, it } from 'vitest'

import { densityToSize } from './tableSettings'

describe('densityToSize 映射', () => {
  it('compact → small / comfortable → middle / spacious → large', () => {
    expect(densityToSize('compact')).toBe('small')
    expect(densityToSize('comfortable')).toBe('middle')
    expect(densityToSize('spacious')).toBe('large')
  })
})

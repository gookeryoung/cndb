/**
 * tableSettings 纯逻辑单元测试 —— localStorage 读写与 density 映射.
 *
 * 覆盖：默认值 / 部分字段合并 / 非法 JSON 容错 / 保存回读 /
 * localStorage 异常静默 / densityToSize 全矩阵。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_TABLE_SETTINGS,
  densityToSize,
  loadTableSettings,
  saveTableSettings,
} from './tableSettings'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('loadTableSettings', () => {
  it('无存储值时返回默认值副本（修改结果不影响默认常量）', () => {
    const s = loadTableSettings()
    expect(s).toEqual(DEFAULT_TABLE_SETTINGS)
    expect(s).not.toBe(DEFAULT_TABLE_SETTINGS)
  })

  it('已存完整设置时原样返回', () => {
    const saved = { ...DEFAULT_TABLE_SETTINGS, density: 'compact' as const, defaultPageSize: 20 }
    localStorage.setItem('cndb_table_settings', JSON.stringify(saved))
    expect(loadTableSettings()).toEqual(saved)
  })

  it('部分字段时与默认值合并（兼容新增字段）', () => {
    localStorage.setItem('cndb_table_settings', JSON.stringify({ density: 'spacious' }))
    const s = loadTableSettings()
    expect(s.density).toBe('spacious')
    expect(s.defaultPageSize).toBe(DEFAULT_TABLE_SETTINGS.defaultPageSize)
    expect(s.newRowPosition).toBe(DEFAULT_TABLE_SETTINGS.newRowPosition)
  })

  it('非法 JSON 时静默回退默认值', () => {
    localStorage.setItem('cndb_table_settings', '{invalid json')
    expect(loadTableSettings()).toEqual(DEFAULT_TABLE_SETTINGS)
  })

  it('localStorage 抛异常时静默回退默认值', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    expect(loadTableSettings()).toEqual(DEFAULT_TABLE_SETTINGS)
  })
})

describe('saveTableSettings', () => {
  it('保存后可回读', () => {
    const s = { ...DEFAULT_TABLE_SETTINGS, newRowPosition: 'top' as const }
    saveTableSettings(s)
    expect(loadTableSettings()).toEqual(s)
  })

  it('localStorage 不可用时静默失败不抛错', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => saveTableSettings(DEFAULT_TABLE_SETTINGS)).not.toThrow()
  })
})

describe('densityToSize 映射', () => {
  it('compact → small / comfortable → middle / spacious → large', () => {
    expect(densityToSize('compact')).toBe('small')
    expect(densityToSize('comfortable')).toBe('middle')
    expect(densityToSize('spacious')).toBe('large')
  })
})

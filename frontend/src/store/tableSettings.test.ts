/** store/tableSettings 单元测试 —— updateSettings 合并与持久化、resetSettings */
import { beforeEach, describe, expect, it } from 'vitest'
import { useTableSettingsStore } from './tableSettings'
import { DEFAULT_TABLE_SETTINGS } from '@/theme/tableSettings'

const STORAGE_KEY = 'cndb_table_settings'

beforeEach(() => {
  useTableSettingsStore.getState().resetSettings()
})

describe('初始状态', () => {
  it('与 DEFAULT_TABLE_SETTINGS 一致', () => {
    const s = useTableSettingsStore.getState()
    expect(s.density).toBe(DEFAULT_TABLE_SETTINGS.density)
    expect(s.defaultPageSize).toBe(DEFAULT_TABLE_SETTINGS.defaultPageSize)
    expect(s.bordered).toBe(DEFAULT_TABLE_SETTINGS.bordered)
    expect(s.showHeader).toBe(DEFAULT_TABLE_SETTINGS.showHeader)
    expect(s.striped).toBe(DEFAULT_TABLE_SETTINGS.striped)
  })
})

describe('updateSettings 批量合并', () => {
  it('只更新传入字段，其余保持不变', () => {
    useTableSettingsStore.getState().updateSettings({ density: 'compact', striped: true })
    const s = useTableSettingsStore.getState()
    expect(s.density).toBe('compact')
    expect(s.striped).toBe(true)
    expect(s.defaultPageSize).toBe(DEFAULT_TABLE_SETTINGS.defaultPageSize)
    expect(s.bordered).toBe(DEFAULT_TABLE_SETTINGS.bordered)
    expect(s.showHeader).toBe(DEFAULT_TABLE_SETTINGS.showHeader)
  })

  it('更新后写入 localStorage（persist 中间件）', () => {
    useTableSettingsStore.getState().updateSettings({ defaultPageSize: 20 })
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).toBeTruthy()
    // zustand persist 写入结构为 { state: {...}, version }
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> }
    expect(persisted.state.defaultPageSize).toBe(20)
  })
})

describe('resetSettings', () => {
  it('重置为默认值并同步持久化', () => {
    useTableSettingsStore.getState().updateSettings({ density: 'spacious', bordered: true })
    useTableSettingsStore.getState().resetSettings()
    const s = useTableSettingsStore.getState()
    expect(s.density).toBe(DEFAULT_TABLE_SETTINGS.density)
    expect(s.bordered).toBe(DEFAULT_TABLE_SETTINGS.bordered)
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY)!) as { state: Record<string, unknown> }
    expect(persisted.state.density).toBe(DEFAULT_TABLE_SETTINGS.density)
  })
})

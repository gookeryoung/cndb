/** 表格/视图全局用户设置 store — localStorage 持久化.
 *
 * 替代原 TableSettingsProvider (React Context).
 * zustand 的 selector 机制确保消费者仅订阅关心的字段，
 * 任何字段变更不会导致无关消费者重渲染。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { DEFAULT_TABLE_SETTINGS, type TableSettings } from '@/theme/tableSettings'

interface TableSettingsState extends TableSettings {
  /** 批量更新 — 传入部分字段，会合并并持久化 */
  updateSettings: (patch: Partial<TableSettings>) => void
  /** 重置为默认值 */
  resetSettings: () => void
}

export const useTableSettingsStore = create<TableSettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_TABLE_SETTINGS,

      updateSettings: (patch) =>
        set((state) => ({ ...state, ...patch })),

      resetSettings: () => set({ ...DEFAULT_TABLE_SETTINGS }),
    }),
    {
      name: 'cndb_table_settings',
      // 默认 merge 已做 { ...initial, ...persisted }，兼容新增字段
    },
  ),
)

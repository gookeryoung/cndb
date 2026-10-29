/** 文档渲染全局用户设置 store — localStorage 持久化.
 *
 * 与 `@/store/tableSettings` 同模式：zustand 的 selector 机制确保消费者
 * 仅订阅关心的字段，任何字段变更不会导致无关消费者重渲染。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { DEFAULT_DOC_SETTINGS, type DocSettings } from '@/theme/docSettings'

interface DocSettingsState extends DocSettings {
  /** 批量更新 — 传入部分字段，会合并并持久化 */
  updateSettings: (patch: Partial<DocSettings>) => void
  /** 重置为默认值 */
  resetSettings: () => void
}

export const useDocSettingsStore = create<DocSettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_DOC_SETTINGS,

      updateSettings: (patch) =>
        set((state) => ({ ...state, ...patch })),

      resetSettings: () => set({ ...DEFAULT_DOC_SETTINGS }),
    }),
    {
      name: 'cndb_doc_settings',
      // 默认 merge 已做 { ...initial, ...persisted }，兼容新增字段
    },
  ),
)

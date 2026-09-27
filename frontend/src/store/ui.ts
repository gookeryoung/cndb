/** 全局 UI 状态 store — 跨层级打开个人设置并定位页签.
 *
 * 场景：Grid 视图栏「表格设置」快捷按钮（GridPage 层）需要打开
 * MainLayout 层挂载的 SettingsModal，通过本 store 解耦层级传递。
 */

import { create } from 'zustand'

/** 个人设置页签 key（与 SettingsModal 的 Tabs items 对应） */
export type SettingsTab = 'profile' | 'theme' | 'table'

interface UiState {
    /** 个人设置 Modal 是否打开 */
    settingsOpen: boolean
    /** 打开时定位的页签 */
    settingsTab: SettingsTab
    /** 打开个人设置，可指定页签（缺省定位「用户资料」） */
    openSettings: (tab?: SettingsTab) => void
    /** 关闭个人设置 */
    closeSettings: () => void
}

export const useUiStore = create<UiState>((set) => ({
    settingsOpen: false,
    settingsTab: 'profile',
    openSettings: (tab) => set({ settingsOpen: true, settingsTab: tab ?? 'profile' }),
    closeSettings: () => set({ settingsOpen: false }),
}))

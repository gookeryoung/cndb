/** 新手引导 onboarding store — localStorage 持久化.
 *
 * tourDone：用户已完成（或跳过）过引导，刷新后不再自动弹出。
 * tourRequested：帮助中心「重新播放新手引导」按钮发出的信号，
 * OnboardingTour 组件监听到 true 后启动引导并清除该标记。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** localStorage 持久化 key —— E2E setup 用它预置完成标记，避免引导干扰存量用例 */
export const TOUR_STORAGE_KEY = 'cndb_onboarding_done_v1'

interface OnboardingState {
    /** 引导是否已完成（含跳过），true 后不再自动触发 */
    tourDone: boolean
    /** 帮助中心请求重放引导的信号 */
    tourRequested: boolean
    /** 标记引导已完成（点击关闭/跳过/走完最后一步） */
    markTourDone: () => void
    /** 帮助中心请求重放引导 */
    requestTour: () => void
    /** 引导启动后清除重放请求 */
    clearTourRequest: () => void
}

export const useOnboardingStore = create<OnboardingState>()(
    persist(
        (set) => ({
            tourDone: false,
            tourRequested: false,

            markTourDone: () => set({ tourDone: true }),
            requestTour: () => set({ tourRequested: true }),
            clearTourRequest: () => set({ tourRequested: false }),
        }),
        {
            name: TOUR_STORAGE_KEY,
            // 仅持久化 tourDone；tourRequested 是会话内信号，重开后不应残留
            partialize: (state) => ({ tourDone: state.tourDone }),
        },
    ),
)

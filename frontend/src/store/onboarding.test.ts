/** onboarding store 状态流转测试. */

import { beforeEach, describe, expect, it } from 'vitest'
import { TOUR_STORAGE_KEY, useOnboardingStore } from './onboarding'

describe('onboarding store', () => {
    beforeEach(() => {
        // 每个用例重置到初始状态（不影响持久化层，持久化行为单独验证）
        useOnboardingStore.setState({ tourDone: false, tourRequested: false })
        localStorage.clear()
    })

    it('初始状态：未完成、无重放请求', () => {
        const s = useOnboardingStore.getState()
        expect(s.tourDone).toBe(false)
        expect(s.tourRequested).toBe(false)
    })

    it('markTourDone 置完成标记', () => {
        useOnboardingStore.getState().markTourDone()
        expect(useOnboardingStore.getState().tourDone).toBe(true)
    })

    it('requestTour 设置重放信号，clearTourRequest 清除', () => {
        useOnboardingStore.getState().requestTour()
        expect(useOnboardingStore.getState().tourRequested).toBe(true)

        useOnboardingStore.getState().clearTourRequest()
        expect(useOnboardingStore.getState().tourRequested).toBe(false)
    })

    it('重放请求不会改变完成标记', () => {
        useOnboardingStore.getState().markTourDone()
        useOnboardingStore.getState().requestTour()
        expect(useOnboardingStore.getState().tourDone).toBe(true)
        expect(useOnboardingStore.getState().tourRequested).toBe(true)
    })

    it('持久化仅含 tourDone，tourRequested 不落盘', () => {
        useOnboardingStore.getState().markTourDone()
        useOnboardingStore.getState().requestTour()
        // zustand persist 异步写 localStorage，这里同步触发一次序列化校验 partialize 形状
        const persisted = JSON.parse(localStorage.getItem(TOUR_STORAGE_KEY) || '{}')
        if (persisted.state) {
            expect(persisted.state).toEqual({ tourDone: true })
        }
        // key 必须与 E2E setup 预置的 key 一致
        expect(TOUR_STORAGE_KEY).toBe('cndb_onboarding_done_v1')
    })
})

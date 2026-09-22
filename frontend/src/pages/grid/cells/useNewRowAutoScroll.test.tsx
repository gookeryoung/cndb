/** useNewRowAutoScroll 回归测试 —— 虚拟表格新增行自动滚动聚焦.
 *
 * 真实浏览器 bug（GridPage 的 jsdom 集成测试无法复现，故单测锁死机制）：
 *   1. 旧实现"先 querySelector 找行、找不到就放弃"—— 虚拟窗口外的行不在 DOM，
 *      守卫必然失败 → 滚动从未发生（只有滚动本身才能让行进入虚拟窗口）；
 *   2. 旧实现传 `scrollTo({ top })` —— rc-virtual-list 虚拟分支完全忽略 top，
 *      仅识别 key/index/align/offset → 空操作。
 *
 * 因此本组用例在"行不在 DOM"的前提下断言：滚动指令必须按 key 发出、
 * 且不得携带 top 字段；行进入 DOM 后第一个可编辑输入框获得焦点。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import type { RefObject } from 'react'
import { useNewRowAutoScroll, type TableScrollTarget } from './useNewRowAutoScroll'

/** 构造 fake tableRef —— 模拟 AntD Table ref 的 scrollTo 入口 */
function makeTableRef(): { ref: RefObject<TableScrollTarget | null>; scrollTo: ReturnType<typeof vi.fn> } {
    const scrollTo = vi.fn()
    const ref: RefObject<TableScrollTarget | null> = { current: { scrollTo } }
    return { ref, scrollTo }
}

/** 往 DOM 挂一个模拟"虚拟滚动后进入窗口"的新增行 */
function mountFakeNewRow(fields: 'text' | 'hidden+text' | 'empty' = 'text'): HTMLInputElement {
    const row = document.createElement('div')
    row.setAttribute('data-row-key', '__new__')
    document.body.appendChild(row)
    if (fields === 'empty') return document.createElement('input')
    if (fields === 'hidden+text') {
        const hidden = document.createElement('input')
        hidden.type = 'hidden'
        row.appendChild(hidden)
    }
    const input = document.createElement('input')
    input.type = 'text'
    row.appendChild(input)
    return input
}

describe('useNewRowAutoScroll（虚拟表格新增行滚动聚焦）', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
    })

    afterEach(() => {
        document.body.innerHTML = ''
    })

    it('page 位置：行不在 DOM 时也必须按 key 发出滚动指令（回归：先找行后滚动的守卫永不通过）', () => {
        const { ref, scrollTo } = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: true, position: 'page', rowDomKey: '__new__', tableRef: ref }),
        )
        expect(scrollTo).toHaveBeenCalledTimes(1)
        expect(scrollTo).toHaveBeenCalledWith({ key: '__new__', align: 'bottom' })
        // 虚拟表格会忽略 top，不得携带该字段
        expect(scrollTo.mock.calls[0][0]).not.toHaveProperty('top')
    })

    it('tail 位置：align=bottom（滚到末行）', () => {
        const { ref, scrollTo } = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: true, position: 'tail', rowDomKey: '__new__', tableRef: ref }),
        )
        expect(scrollTo).toHaveBeenCalledWith({ key: '__new__', align: 'bottom' })
    })

    it('top 位置：align=top（滚到首行）', () => {
        const { ref, scrollTo } = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: true, position: 'top', rowDomKey: '__new__', tableRef: ref }),
        )
        expect(scrollTo).toHaveBeenCalledWith({ key: '__new__', align: 'top' })
    })

    it('行进入 DOM 后聚焦其第一个可编辑输入框', async () => {
        const { ref } = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: true, position: 'page', rowDomKey: '__new__', tableRef: ref }),
        )
        const input = mountFakeNewRow()
        await waitFor(() => expect(document.activeElement).toBe(input))
    })

    it('聚焦时跳过隐藏输入框与复选框', async () => {
        const { ref } = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: true, position: 'page', rowDomKey: '__new__', tableRef: ref }),
        )
        const input = mountFakeNewRow('hidden+text')
        await waitFor(() => expect(document.activeElement).toBe(input))
    })

    it('行始终未进入 DOM 时轮询有界，不无限循环', async () => {
        vi.useFakeTimers()
        try {
            const { ref, scrollTo } = makeTableRef()
            renderHook(() =>
                useNewRowAutoScroll({ active: true, enabled: true, position: 'page', rowDomKey: '__new__', tableRef: ref }),
            )
            // 推进远超 60 帧的时间：无行可聚焦时轮询应自行停止（无异常即通过）
            vi.advanceTimersByTime(5000)
            expect(scrollTo).toHaveBeenCalledTimes(1)
        } finally {
            vi.useRealTimers()
        }
    })

    it('active=false 或 enabled=false 时不滚动', () => {
        const a = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: false, enabled: true, position: 'page', rowDomKey: '__new__', tableRef: a.ref }),
        )
        const b = makeTableRef()
        renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: false, position: 'page', rowDomKey: '__new__', tableRef: b.ref }),
        )
        expect(a.scrollTo).not.toHaveBeenCalled()
        expect(b.scrollTo).not.toHaveBeenCalled()
    })

    it('props 不变的重渲染不重复滚动', () => {
        const { ref, scrollTo } = makeTableRef()
        const { rerender } = renderHook(
            (props: { position: 'top' | 'tail' | 'page' }) =>
                useNewRowAutoScroll({ active: true, enabled: true, rowDomKey: '__new__', tableRef: ref, ...props }),
            { initialProps: { position: 'page' as const } },
        )
        rerender({ position: 'page' })
        rerender({ position: 'page' })
        expect(scrollTo).toHaveBeenCalledTimes(1)
    })

    it('resyncSignal 变化时重新发出滚动指令（tail 跳页数据到达后二次校准）', () => {
        const { ref, scrollTo } = makeTableRef()
        const { rerender } = renderHook(
            ({ signal }) =>
                useNewRowAutoScroll({
                    active: true, enabled: true, position: 'tail', rowDomKey: '__new__', tableRef: ref, resyncSignal: signal,
                }),
            { initialProps: { signal: 5 } },
        )
        expect(scrollTo).toHaveBeenCalledTimes(1)
        rerender({ signal: 20 })
        expect(scrollTo).toHaveBeenCalledTimes(2)
    })

    it('卸载后停止聚焦轮询', async () => {
        const { ref } = makeTableRef()
        const { unmount } = renderHook(() =>
            useNewRowAutoScroll({ active: true, enabled: true, position: 'page', rowDomKey: '__new__', tableRef: ref }),
        )
        unmount()
        // 卸载后才把行挂进 DOM：轮询已取消，输入框不应获得焦点
        const input = mountFakeNewRow()
        await new Promise(resolve => setTimeout(resolve, 120))
        expect(document.activeElement).not.toBe(input)
    })
})

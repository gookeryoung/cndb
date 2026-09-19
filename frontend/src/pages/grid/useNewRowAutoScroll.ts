/**
 * 新增行自动滚动聚焦 hook.
 *
 * 背景（真实浏览器回归 bug，jsdom 无法复现）：
 *   AntD 虚拟表格下，目标行不在可见窗口时根本不在 DOM 中。旧实现"先 querySelector
 *   找行、找不到就放弃"导致滚动从未发生（只有滚动本身才能让行进入虚拟窗口）；
 *   且 `scrollTo({ top })` 在虚拟模式下会被 rc-virtual-list 完全忽略（仅非虚拟的
 *   原生滚动分支才读 top），传 `Number.MAX_SAFE_INTEGER` 同样是空操作。
 *
 * 正确策略：
 *   1. 先滚后聚焦 —— 无条件调用 `scrollTo({ key, align })`，按行 key 滚动是
 *      rc-table 虚拟/非虚拟两种 body 实现都支持的唯一入口；
 *   2. 有界 rAF 轮询等行进入虚拟窗口（高度收敛最多 10 帧，留足余量）后聚焦
 *      第一个可编辑单元格，超时静默放弃，避免无限循环。
 */
import { useEffect } from 'react'
import type { Key, RefObject } from 'react'

/** 与 rc-table Reference.scrollTo 兼容的结构类型（虚拟模式仅识别 key/index/align/offset） */
export interface TableScrollTarget {
    scrollTo: (opts: {
        key?: Key
        index?: number
        align?: 'top' | 'bottom' | 'auto'
        offset?: number
        top?: number
        left?: number
    }) => void
}

/** 聚焦轮询上限（帧）：覆盖虚拟滚动高度收敛（rc-virtual-list MAX_TIMES=10）+ 渲染耗时 */
const FOCUS_POLL_MAX_FRAMES = 60

/** 新增行激活后自动滚动到新行并聚焦第一个可编辑单元格 */
export function useNewRowAutoScroll(params: {
    /** 新增行是否激活 */
    active: boolean
    /** 总开关（如仅 grid 视图生效） */
    enabled: boolean
    /** 新增行位置：top 滚到首行，tail/page 滚到末行 */
    position: 'top' | 'tail' | 'page'
    /** 行的 data-row-key 值 */
    rowDomKey: Key
    /** AntD Table ref —— 虚拟滚动下唯一正确的滚动入口 */
    tableRef: RefObject<TableScrollTarget | null>
    /** 重同步信号：tail 跳页后数据到达（行数变化）时重新校准滚动位置 */
    resyncSignal?: number
}): void {
    const { active, enabled, position, rowDomKey, tableRef, resyncSignal } = params

    useEffect(() => {
        if (!active || !enabled) return

        // 关键：先滚 —— 不做任何 DOM 前置检查（虚拟窗口外行不存在，检查必然失败）
        tableRef.current?.scrollTo({
            key: rowDomKey,
            align: position === 'top' ? 'top' : 'bottom',
        })

        // 后聚焦 —— 有界轮询等虚拟滚动把行渲染进窗口
        let rafId = 0
        let frames = 0
        const tryFocus = () => {
            const row = document.querySelector(`[data-row-key="${CSS.escape(String(rowDomKey))}"]`) as HTMLElement | null
            if (row) {
                const firstInput = row.querySelector<HTMLElement>(
                    'input:not([type="hidden"]):not(.ant-checkbox-input), textarea, [role="combobox"], .ant-picker',
                )
                firstInput?.focus()
                return
            }
            if (++frames < FOCUS_POLL_MAX_FRAMES) rafId = requestAnimationFrame(tryFocus)
        }
        rafId = requestAnimationFrame(tryFocus)
        return () => cancelAnimationFrame(rafId)
    }, [active, enabled, position, rowDomKey, tableRef, resyncSignal])
}

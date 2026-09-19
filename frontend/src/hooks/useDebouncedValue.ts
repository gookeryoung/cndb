import { useEffect, useState } from 'react'

/**
 * 值防抖 Hook —— 源值高频变化时，仅在其停止变化 delayMs 毫秒后才更新返回值.
 *
 * 典型场景：搜索输入防抖、预览渲染结果防抖（如 PreviewPanel 的 300ms 渲染防抖）.
 *
 * @param value   源值（每次 render 都可能是新引用）
 * @param delayMs 防抖窗口（毫秒）；窗口内值再次变化会重置计时器
 * @returns 防抖后的值（稳定引用，窗口期内保持旧值）
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
    const [debounced, setDebounced] = useState(value)

    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delayMs)
        return () => clearTimeout(timer)
    }, [value, delayMs])

    return debounced
}

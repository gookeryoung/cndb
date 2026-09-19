import { useCallback, useEffect, useRef } from 'react'

/**
 * 回调防抖 Hook —— 返回防抖版回调与取消函数.
 *
 * 语义要点：
 * - 内部用 ref 保存最新回调，调用点无需 useCallback 包裹传入的 fn；
 * - 组件卸载时自动取消 pending 调用，避免组件销毁后触发副作用；
 * - "依赖变更即取消 pending"（如 GridPage 视图配置自动保存：dep 变化先清旧计时器
 *   再重新计时）由调用点在 effect cleanup 中显式调用返回的 cancel 实现.
 *
 * @param fn      需要防抖的回调（每次 render 传入新引用也安全）
 * @param delayMs 防抖窗口（毫秒）
 * @returns [run, cancel] —— run 防抖版回调（参数原样透传给最后一次调用），cancel 取消 pending
 */
export function useDebouncedCallback<F extends (...args: never[]) => void>(
  fn: F,
  delayMs: number,
): [run: (...args: Parameters<F>) => void, cancel: () => void] {
  const fnRef = useRef(fn)

  useEffect(() => {
    fnRef.current = fn
  }, [fn])

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancel = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // 卸载兜底：取消未执行的 pending 调用
  useEffect(() => cancel, [cancel])

  const run = useCallback(
    (...args: Parameters<F>) => {
      cancel()
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        fnRef.current(...args)
      }, delayMs)
    },
    [cancel, delayMs],
  )

  return [run, cancel]
}

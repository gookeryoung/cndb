import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'

export interface ElementSize {
  width: number
  height: number
}

/**
 * 容器尺寸测量 Hook —— 返回 ref 与元素实时尺寸.
 *
 * 双通道测量（对齐 GridPage 原 gridAreaSize 实现）：
 * - ResizeObserver 观察元素自身尺寸变化（flex 布局、内容伸缩等）；
 * - window.resize 兜底（覆盖部分浏览器下 ResizeObserver 不触发的场景）.
 *
 * @param initial 初始尺寸（首帧渲染、ref 未挂载时使用，可避免 scroll.y 等派生值抖动）
 * @returns [ref, size] —— ref 绑定到目标元素，size 实时更新
 */
export function useElementSize<T extends HTMLElement>(
  initial: ElementSize = { width: 0, height: 0 },
): [RefObject<T>, ElementSize] {
  const ref = useRef<T>(null)
  const [size, setSize] = useState<ElementSize>(initial)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    update()

    const ro = new ResizeObserver(update)
    ro.observe(el)
    window.addEventListener('resize', update)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])

  return [ref, size]
}

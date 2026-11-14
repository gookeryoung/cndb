/** 文档「并排查看」滚动同步：编辑栏与预览栏作为一组，滚动任意一侧另一侧跟随.
 *
 * 设计要点：
 * - 两栏渲染高度不同（编辑器行高 vs 渲染元素高度），按**滚动进度比例**对齐，
 *   而不是逐像素拷贝 `scrollTop`，避免长文档下半部分严重错位。
 * - 只同步纵向；目标栏无可滚动空间（内容未超出视口）时不强行拉回另一栏。
 * - 程序化设置 `scrollTop` 会回抛 scroll 事件：用「已就位则不动」让回声自然终止。
 * - 监听挂在两栏根节点上（capture 阶段），编辑器实现（CodeMirror `.cm-scroller` / 源码
 *   textarea）无需暴露滚动容器。
 */

import { useEffect, type RefObject } from 'react'

/** 滚动进度：`scrollTop / (scrollHeight - clientHeight)`，无滚动空间时返回 0 */
export function scrollProgress({
  scrollTop,
  scrollHeight,
  clientHeight,
}: Pick<HTMLElement, 'scrollTop' | 'scrollHeight' | 'clientHeight'>): number {
  const max = scrollHeight - clientHeight
  if (!(max > 0)) return 0
  const ratio = scrollTop / max
  return ratio <= 0 ? 0 : ratio >= 1 ? 1 : ratio
}

/** 把滚动进度应用到目标元素；返回是否真的移动了（无滚动空间 / 已就位时为 false） */
export function applyScrollProgress(el: HTMLElement, progress: number): boolean {
  const max = el.scrollHeight - el.clientHeight
  if (!(max > 0)) return false
  const clamped = progress <= 0 ? 0 : progress >= 1 ? 1 : progress
  const next = Math.round(clamped * max)
  if (Math.abs(el.scrollTop - next) <= 1) return false
  el.scrollTop = next
  return true
}

/** 找到 root 内实际纵向滚动的元素：root 自身或第一个内容超高的后代 */
export function findScrollHost(root: HTMLElement | null): HTMLElement | null {
  if (!root) return null
  const candidates = [root, ...Array.from(root.querySelectorAll<HTMLElement>('*'))]
  for (const el of candidates) {
    if (el.scrollHeight - el.clientHeight > 0) return el
  }
  return null
}

/** 并排查看滚动同步：active 为 false 时不监听（单栏 / 窄屏 / 原件族文档） */
export function useSplitScrollSync(
  leftRef: RefObject<HTMLElement | null>,
  rightRef: RefObject<HTMLElement | null>,
  active: boolean,
): void {
  useEffect(() => {
    if (!active) return
    const leftRoot = leftRef.current
    const rightRoot = rightRef.current
    if (!leftRoot || !rightRoot) return

    // 目标栏滚动容器缓存：内容变长后（首次解析为 null）下次滚动重新解析
    const hostCache = new Map<HTMLElement, HTMLElement | null>()
    const resolveHost = (root: HTMLElement): HTMLElement | null => {
      const cached = hostCache.get(root)
      if (cached?.isConnected && cached.scrollHeight - cached.clientHeight > 0) return cached
      const host = findScrollHost(root)
      hostCache.set(root, host)
      return host
    }

    // 不加帧锁：目标栏回抛的 scroll 会算出同一进度，`applyScrollProgress` 的
    // 「已就位则不动」直接把它变成 no-op，回声自然终止且不吞掉用户连续滚动
    const sync = (from: EventTarget | null, toRoot: HTMLElement) => {
      if (!(from instanceof HTMLElement)) return
      // 只响应纵向滚动：预览 / 编辑器内横向滚动的块（宽表格等）没有纵向行程，不得把另一栏拉回顶部
      if (from.scrollHeight - from.clientHeight <= 0) return
      const to = resolveHost(toRoot)
      if (!to) return
      applyScrollProgress(to, scrollProgress(from))
    }

    const onLeftScroll = (e: Event) => sync(e.target, rightRoot)
    const onRightScroll = (e: Event) => sync(e.target, leftRoot)
    leftRoot.addEventListener('scroll', onLeftScroll, true)
    rightRoot.addEventListener('scroll', onRightScroll, true)
    return () => {
      leftRoot.removeEventListener('scroll', onLeftScroll, true)
      rightRoot.removeEventListener('scroll', onRightScroll, true)
    }
  }, [active, leftRef, rightRef])
}

/** 顶部导航横滑辅助 —— 工作区页签 + 二级页签在窄屏下横向滚动时，把激活项滚入可视区.
 *
 * 仅调整容器自身的 `scrollLeft`（不调用 `scrollIntoView`，避免连带滚动整页），
 * 因此桌面端无溢出时为无副作用空操作。
 */

/** 容器内「激活页签」选择器：antd Tabs 激活项 + 表级/文档级胶囊页签激活项 */
const ACTIVE_TAB_SELECTOR = '.ant-tabs-tab-active, .cn-table-tab-active'

/** 激活项滚入可视区两侧各留的余量（px），避免贴着边缘 */
const DEFAULT_PADDING = 12

/** 把激活页签滚入容器可视区；容器/激活项缺失或尚未布局时安全返回.
 *
 * 同一行可能同时存在两级激活项（工作区页签 + 二级页签），取**最后一个**（最具体的那一级，
 * 即用户当前所在子页）作为滚动目标；只有一级激活时行为不变。 */
export function scrollActiveTabIntoView(container: HTMLElement | null, padding = DEFAULT_PADDING): void {
  if (!container) return
  const actives = container.querySelectorAll(ACTIVE_TAB_SELECTOR)
  if (actives.length === 0) return
  const active = actives[actives.length - 1] as HTMLElement

  const c = container.getBoundingClientRect()
  const a = active.getBoundingClientRect()
  // 尚未布局（jsdom / 首帧）时宽高为 0，不做无意义的滚动
  if (a.width === 0 && a.height === 0) return
  if (a.left < c.left) {
    container.scrollLeft -= c.left - a.left + padding
  } else if (a.right > c.right) {
    container.scrollLeft += a.right - c.right + padding
  }
}

/** 下一帧执行（等 antd Tabs 指示条布局完成后测量），返回取消函数. */
export function scrollActiveTabIntoViewNextFrame(container: HTMLElement | null, padding = DEFAULT_PADDING): () => void {
  if (typeof requestAnimationFrame !== 'function') {
    scrollActiveTabIntoView(container, padding)
    return () => { /* noop */ }
  }
  const raf = requestAnimationFrame(() => scrollActiveTabIntoView(container, padding))
  return () => cancelAnimationFrame(raf)
}

export { ACTIVE_TAB_SELECTOR, DEFAULT_PADDING }

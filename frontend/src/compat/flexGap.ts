/** flex gap 垫片 —— 仅旧内核动态加载：读取计算后的 gap 并补子元素 margin。
 *
 * 覆盖三类布局：单行横向补 margin-left、单列纵向补 margin-top、
 * 换行布局给子元素补 right/bottom margin 并用容器负 margin 抵消首尾空隙。
 * 同时覆盖业务内联 gap、CSS 类与 antd Space / Grid 的运行时 rowGap/columnGap（ADR 0026 D5）。
 */

import { isFlexGapSupported } from './flexGapSupport'

export { isFlexGapSupported }

type MarginProp = 'marginLeft' | 'marginTop' | 'marginRight' | 'marginBottom'

const MARGIN_CSS: Record<MarginProp, string> = {
  marginLeft: 'margin-left',
  marginTop: 'margin-top',
  marginRight: 'margin-right',
  marginBottom: 'margin-bottom',
}

interface SavedChild {
  el: HTMLElement
  margins: Partial<Record<MarginProp, string>>
}

interface Applied {
  containerMargins: Partial<Record<MarginProp, string>>
  children: SavedChild[]
}

const appliedContainers = new WeakMap<HTMLElement, Applied>()

const SHIM_CLASS = 'cn-no-flex-gap'

/** 现场 kill switch：置 true 后已生效的 margin 会在下一次扫描时还原 */
function shimDisabled(): boolean {
  if (typeof window === 'undefined') return false
  return Boolean((window as unknown as Record<string, unknown>).__CNDB_DISABLE_FLEX_GAP_SHIM__)
}

function parseGapLength(raw: string | null | undefined): number | null {
  if (!raw) return null
  const value = raw.trim()
  if (!value || value === 'normal') return null
  const m = /^(-?\d*\.?\d+)(px)?$/.exec(value)
  if (!m) return null
  return Math.max(0, Number.parseFloat(m[1]))
}

function parseGapShorthand(raw: string | null | undefined): { row: number; column: number } {
  if (!raw) return { row: 0, column: 0 }
  const parts = raw.trim().split(/\s+/)
  const row = parseGapLength(parts[0]) ?? 0
  const column = parseGapLength(parts[1]) ?? row
  return { row, column }
}

/** 读取容器声明的 gap；row-gap / column-gap 为 normal 时回落到 gap 简写 */
export function readFlexGaps(el: Element): { rowGap: number; columnGap: number } {
  const style = getComputedStyle(el)
  const shorthand = parseGapShorthand(style.getPropertyValue('gap'))
  const rowGap = parseGapLength(style.getPropertyValue('row-gap')) ?? shorthand.row
  const columnGap = parseGapLength(style.getPropertyValue('column-gap')) ?? shorthand.column
  return { rowGap, columnGap }
}

function restore(el: HTMLElement): void {
  const record = appliedContainers.get(el)
  if (!record) return
  appliedContainers.delete(el)
  for (const child of record.children) {
    for (const [prop, original] of Object.entries(child.margins) as [MarginProp, string][]) {
      if (original) child.el.style.setProperty(MARGIN_CSS[prop], original)
      else child.el.style.removeProperty(MARGIN_CSS[prop])
    }
  }
  for (const [prop, original] of Object.entries(record.containerMargins) as [MarginProp, string][]) {
    if (original) el.style.setProperty(MARGIN_CSS[prop], original)
    else el.style.removeProperty(MARGIN_CSS[prop])
  }
}

function isHorizontal(direction: string): boolean {
  return direction === 'row' || direction === 'row-reverse'
}

function shimContainer(el: HTMLElement): void {
  restore(el)
  if (shimDisabled()) return

  const style = getComputedStyle(el)
  if (style.display !== 'flex' && style.display !== 'inline-flex') return

  const { rowGap, columnGap } = readFlexGaps(el)
  if (rowGap <= 0 && columnGap <= 0) return

  const children = Array.from(el.children).filter((child): child is HTMLElement => {
    if (!(child instanceof HTMLElement)) return false
    const childStyle = getComputedStyle(child)
    if (childStyle.display === 'none') return false
    return childStyle.position !== 'absolute' && childStyle.position !== 'fixed'
  })
  if (children.length < 2) return

  const direction = style.flexDirection || 'row'
  const wraps = (style.flexWrap || 'nowrap') !== 'nowrap'
  const horizontal = isHorizontal(direction)

  const record: Applied = { containerMargins: {}, children: [] }
  const childrenAt = new Map<HTMLElement, SavedChild>()
  const saveChild = (child: HTMLElement, prop: MarginProp) => {
    let saved = childrenAt.get(child)
    if (!saved) {
      saved = { el: child, margins: {} }
      childrenAt.set(child, saved)
      record.children.push(saved)
    }
    if (!(prop in saved.margins)) saved.margins[prop] = child.style.getPropertyValue(MARGIN_CSS[prop])
    return saved
  }
  const addMargin = (child: HTMLElement, prop: MarginProp, delta: number) => {
    saveChild(child, prop)
    const base = Number.parseFloat(getComputedStyle(child)[prop]) || 0
    child.style.setProperty(MARGIN_CSS[prop], `${base + delta}px`)
  }
  const saveContainer = (prop: MarginProp) => {
    record.containerMargins[prop] = el.style.getPropertyValue(MARGIN_CSS[prop])
    return Number.parseFloat(getComputedStyle(el)[prop]) || 0
  }

  if (!wraps) {
    // 单行 / 单列：只有相邻元素之间需要间距
    const gap = horizontal ? columnGap : rowGap
    const prop: MarginProp = horizontal ? 'marginLeft' : 'marginTop'
    if (gap <= 0) return
    for (const child of children.slice(1)) addMargin(child, prop, gap)
  } else {
    // 换行：子元素统一补 right/bottom，容器负 margin 抵消末列末行多出的空隙
    if (columnGap > 0) {
      for (const child of children) addMargin(child, 'marginRight', columnGap)
      el.style.setProperty('margin-right', `${saveContainer('marginRight') - columnGap}px`)
    }
    if (rowGap > 0) {
      for (const child of children) addMargin(child, 'marginBottom', rowGap)
      el.style.setProperty('margin-bottom', `${saveContainer('marginBottom') - rowGap}px`)
    }
  }

  if (record.children.length) appliedContainers.set(el, record)
}

/** 对 root 自身及其后代应用垫片（测试与首次全量扫描共用） */
export function applyFlexGapShim(root: ParentNode): void {
  const elements: HTMLElement[] = []
  if (root instanceof HTMLElement) elements.push(root)
  for (const node of root.querySelectorAll<HTMLElement>('*')) elements.push(node)
  for (const el of elements) shimContainer(el)
}

interface IdleDeadlineLike {
  timeRemaining: () => number
}

const pending: HTMLElement[] = []
let scheduled = false
let activeDoc: Document | null = null

function scheduleScan(doc: Document, roots?: HTMLElement[]): void {
  if (roots) pending.push(...roots)
  if (scheduled) return
  scheduled = true
  activeDoc = doc
  const run = (deadline?: IdleDeadlineLike) => {
    scheduled = false
    const started = Date.now()
    while (pending.length) {
      if (deadline ? deadline.timeRemaining() < 4 : Date.now() - started > 12) break
      const root = pending.shift()!
      applyFlexGapShim(root)
    }
    if (pending.length && activeDoc) scheduleScan(activeDoc)
  }
  const ric = typeof window !== 'undefined' ? window.requestIdleCallback : undefined
  if (ric) ric(run)
  else setTimeout(run, 0)
}

/** 装载垫片：打标记类、首次全量扫描、监听后续 DOM 变更；返回清理函数 */
export function initFlexGapShim(doc?: Document): () => void {
  const target = doc ?? (typeof document !== 'undefined' ? document : null)
  if (!target || !target.body || isFlexGapSupported(target)) return () => {}

  target.documentElement.classList.add(SHIM_CLASS)
  scheduleScan(target, [target.body])

  const observer = new MutationObserver(records => {
    const roots: HTMLElement[] = []
    for (const record of records) {
      if (record.type === 'childList') {
        record.addedNodes.forEach(node => {
          if (node instanceof HTMLElement) roots.push(node)
        })
      } else if (record.target instanceof HTMLElement) {
        roots.push(record.target)
      }
    }
    if (roots.length && activeDoc) scheduleScan(activeDoc, roots)
  })
  observer.observe(target.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style'],
  })

  return () => {
    observer.disconnect()
    pending.length = 0
    activeDoc = null
  }
}

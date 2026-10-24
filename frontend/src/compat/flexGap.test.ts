/** flexGap 单元测试 —— 真实布局探测、gap 解析、三类间距规则、还原与 kill switch */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  applyFlexGapShim,
  initFlexGapShim,
  isFlexGapSupported,
  readFlexGaps,
} from './flexGap'

function rect(left: number, right: number): DOMRect {
  return {
    left,
    right,
    top: 0,
    bottom: 10,
    width: right - left,
    height: 10,
    x: left,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect
}

function mockProbeGap(supported: boolean) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const kind = this.getAttribute('data-cn-flex-probe')
    if (kind === 'a') return rect(0, 10)
    if (kind === 'b') return rect(supported ? 20 : 10, supported ? 30 : 20)
    return rect(0, 0)
  })
}

function container(css: string, count = 3): HTMLDivElement {
  const el = document.createElement('div')
  el.style.cssText = css
  for (let i = 0; i < count; i++) {
    const child = document.createElement('span')
    child.textContent = String(i)
    el.appendChild(child)
  }
  document.body.appendChild(el)
  return el
}

function children(el: Element): HTMLElement[] {
  return Array.from(el.children) as HTMLElement[]
}

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
  delete (window as unknown as Record<string, unknown>).__CNDB_DISABLE_FLEX_GAP_SHIM__
})

describe('isFlexGapSupported', () => {
  it('按真实布局量出 10px 间距时判定支持', () => {
    mockProbeGap(true)
    expect(isFlexGapSupported()).toBe(true)
  })

  it('grid gap 为真但 flex gap 为假时判定不支持', () => {
    mockProbeGap(false)
    expect(CSS.supports('gap', '1px')).toBe(true)
    expect(isFlexGapSupported()).toBe(false)
  })
})

describe('readFlexGaps', () => {
  it('解析 gap 简写的单值 / 双值', () => {
    const single = container('display:flex;gap:10px')
    expect(readFlexGaps(single)).toEqual({ rowGap: 10, columnGap: 10 })

    const double = container('display:flex;gap:10px 20px')
    expect(readFlexGaps(double)).toEqual({ rowGap: 10, columnGap: 20 })
  })

  it('row-gap / column-gap 独占声明优先于简写', () => {
    const el = container('display:flex;row-gap:4px;column-gap:6px')
    expect(readFlexGaps(el)).toEqual({ rowGap: 4, columnGap: 6 })
  })

  it('gap: 0 / normal 视为无间距', () => {
    expect(readFlexGaps(container('display:flex;gap:0'))).toEqual({ rowGap: 0, columnGap: 0 })
  })
})

describe('applyFlexGapShim', () => {
  it('单行横向：只有相邻元素之间补 margin-left', () => {
    const el = container('display:flex;gap:10px')
    applyFlexGapShim(el)

    const [a, b, c] = children(el)
    expect(a.style.marginLeft).toBe('')
    expect(b.style.marginLeft).toBe('10px')
    expect(c.style.marginLeft).toBe('10px')
  })

  it('单列纵向：只有相邻元素之间补 margin-top', () => {
    const el = container('display:flex;flex-direction:column;gap:8px')
    applyFlexGapShim(el)

    const [a, b, c] = children(el)
    expect(a.style.marginTop).toBe('')
    expect(b.style.marginTop).toBe('8px')
    expect(c.style.marginTop).toBe('8px')
  })

  it('换行布局：子元素补 right/bottom，容器负 margin 抵消首尾空隙', () => {
    const el = container('display:flex;flex-wrap:wrap;gap:10px 20px')
    applyFlexGapShim(el)

    for (const child of children(el)) {
      expect(child.style.marginRight).toBe('20px')
      expect(child.style.marginBottom).toBe('10px')
    }
    expect(el.style.marginRight).toBe('-20px')
    expect(el.style.marginBottom).toBe('-10px')
  })

  it('已有 margin 叠加，重复应用不累加', () => {
    const el = container('display:flex;gap:10px')
    const second = children(el)[1]
    second.style.marginLeft = '4px'

    applyFlexGapShim(el)
    expect(second.style.marginLeft).toBe('14px')

    applyFlexGapShim(el)
    expect(second.style.marginLeft).toBe('14px')
  })

  it('间距移除后还原原始 margin', () => {
    const el = container('display:flex;gap:10px')
    const second = children(el)[1]
    second.style.marginLeft = '4px'
    applyFlexGapShim(el)
    expect(second.style.marginLeft).toBe('14px')

    el.style.gap = '0px'
    applyFlexGapShim(el)
    expect(second.style.marginLeft).toBe('4px')
    expect(children(el)[2].style.marginLeft).toBe('')
  })

  it('跳过 grid 容器与绝对定位子元素', () => {
    const grid = container('display:grid;gap:10px')
    applyFlexGapShim(grid)
    expect(children(grid)[1].style.marginLeft).toBe('')

    const flex = container('display:flex;gap:10px')
    children(flex)[1].style.position = 'absolute'
    applyFlexGapShim(flex)
    expect(children(flex)[1].style.marginLeft).toBe('')
    expect(children(flex)[2].style.marginLeft).toBe('10px')
  })

  it('kill switch 生效时不再补 margin，并还原已应用的间距', () => {
    const el = container('display:flex;gap:10px')
    applyFlexGapShim(el)
    expect(children(el)[1].style.marginLeft).toBe('10px')

    ;(window as unknown as Record<string, unknown>).__CNDB_DISABLE_FLEX_GAP_SHIM__ = true
    applyFlexGapShim(el)
    expect(children(el)[1].style.marginLeft).toBe('')
  })
})

describe('initFlexGapShim', () => {
  it('旧内核：打标记类并在空闲时完成首次扫描', () => {
    vi.useFakeTimers()
    mockProbeGap(false)
    const el = container('display:flex;gap:10px')

    const cleanup = initFlexGapShim()
    expect(document.documentElement.classList.contains('cn-no-flex-gap')).toBe(true)

    vi.runAllTimers()
    expect(children(el)[1].style.marginLeft).toBe('10px')

    cleanup()
    document.documentElement.classList.remove('cn-no-flex-gap')
    vi.useRealTimers()
  })

  it('现代内核：不打标记类，也不扫描', () => {
    vi.useFakeTimers()
    mockProbeGap(true)
    const el = container('display:flex;gap:10px')

    const cleanup = initFlexGapShim()
    vi.runAllTimers()
    expect(document.documentElement.classList.contains('cn-no-flex-gap')).toBe(false)
    expect(children(el)[1].style.marginLeft).toBe('')

    cleanup()
    vi.useRealTimers()
  })
})

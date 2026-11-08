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
  vi.unstubAllGlobals()
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

describe('initFlexGapShim 增量扫描（ADR 0117 C4）', () => {
  /** 推进假定时器并让 MutationObserver 的微任务回调落地 */
  async function flush() {
    await Promise.resolve()
    await Promise.resolve()
    vi.runAllTimers()
    await Promise.resolve()
  }

  it('新增子树在空闲切片中补上间距', async () => {
    vi.useFakeTimers()
    mockProbeGap(false)
    const cleanup = initFlexGapShim()
    await flush()

    const el = container('display:flex;gap:10px')
    await flush()
    expect(children(el)[1].style.marginLeft).toBe('10px')

    cleanup()
    vi.useRealTimers()
  })

  it('class / style 变更只浅扫自身，不展开整棵子树', async () => {
    vi.useFakeTimers()
    mockProbeGap(false)
    document.body.innerHTML = '<div id="wrap"><div style="display:flex;gap:10px"><span>a</span><span>b</span></div></div>'
    const cleanup = initFlexGapShim()
    await flush()

    const spy = vi.spyOn(Element.prototype, 'querySelectorAll')
    document.body.classList.add('theme-modern')
    await flush()
    expect(spy).not.toHaveBeenCalled()

    cleanup()
    vi.useRealTimers()
  })

  it('垫片自身写入的 style 不触发二次扫描', async () => {
    vi.useFakeTimers()
    mockProbeGap(false)
    container('display:flex;gap:10px')
    const cleanup = initFlexGapShim()
    await flush()

    const spy = vi.spyOn(window, 'getComputedStyle')
    vi.runAllTimers()
    await flush()
    expect(spy).not.toHaveBeenCalled()

    cleanup()
    vi.useRealTimers()
  })

  it('深扫在空闲预算耗尽时中断，下一片从断点继续', () => {
    mockProbeGap(false)
    document.body.innerHTML = `
      <div id="root">
        <div id="a" style="display:flex;gap:10px"><span>a1</span><span>a2</span></div>
        <div id="b" style="display:flex;gap:10px"><span>b1</span><span>b2</span></div>
      </div>`
    const queue: Array<() => void> = []
    const remaining = [5, 5, 3, 30, 30, 30, 30, 30, 30, 30]
    vi.stubGlobal('requestIdleCallback', (cb: IdleRequestCallback) => {
      queue.push(() => cb({ timeRemaining: () => remaining.shift() ?? 30, didTimeout: false } as IdleDeadline))
      return queue.length
    })
    const cleanup = initFlexGapShim()
    const a2 = document.querySelector('#a span:nth-child(2)') as HTMLElement
    const b2 = document.querySelector('#b span:nth-child(2)') as HTMLElement

    // 第一片只处理 body 与 #root，预算耗尽后剩余子树必须留到下一片
    queue.shift()!()
    expect([a2.style.marginLeft, b2.style.marginLeft]).not.toEqual(['10px', '10px'])
    while (queue.length) queue.shift()!()
    expect(a2.style.marginLeft).toBe('10px')
    expect(b2.style.marginLeft).toBe('10px')

    cleanup()
  })
})

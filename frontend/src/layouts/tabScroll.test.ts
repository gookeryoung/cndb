/** tabScroll 纯逻辑测试 —— 顶部导航激活页签滚入可视区. */

import { describe, expect, it, vi } from 'vitest'

import { scrollActiveTabIntoView, scrollActiveTabIntoViewNextFrame } from './tabScroll'

/** 构造带指定 boundingRect 的假元素 */
function el(rect: Partial<DOMRect>, className = ''): HTMLElement {
  const node = document.createElement('button')
  node.className = className
  node.getBoundingClientRect = () =>
    ({ left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...rect }) as DOMRect
  return node
}

function container(rect: Partial<DOMRect>, children: HTMLElement[] = []): HTMLElement {
  const node = document.createElement('div')
  node.getBoundingClientRect = () =>
    ({ left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...rect }) as DOMRect
  for (const child of children) node.appendChild(child)
  return node
}

describe('scrollActiveTabIntoView', () => {
  it('激活项在容器右侧之外：向右滚动到可见并留 12px 余量', () => {
    const active = el({ left: 420, right: 480, width: 60, height: 28 }, 'cn-table-tab cn-table-tab-active')
    const box = container({ left: 0, right: 390, width: 390, height: 36 }, [active])

    scrollActiveTabIntoView(box)

    // (480 - 390) + 12
    expect(box.scrollLeft).toBe(102)
  })

  it('激活项在容器左侧之外：向左回滚', () => {
    const active = el({ left: 20, right: 80, width: 60, height: 28 }, 'ant-tabs-tab-active')
    const box = container({ left: 40, right: 430, width: 390, height: 36 }, [active])
    box.scrollLeft = 200

    scrollActiveTabIntoView(box)

    // 200 - ((40 - 20) + 12)
    expect(box.scrollLeft).toBe(168)
  })

  it('激活项已完整可见：不滚动', () => {
    const active = el({ left: 100, right: 160, width: 60, height: 28 }, 'cn-table-tab-active')
    const box = container({ left: 0, right: 390, width: 390, height: 36 }, [active])
    box.scrollLeft = 30

    scrollActiveTabIntoView(box)

    expect(box.scrollLeft).toBe(30)
  })

  it('自定义余量生效', () => {
    const active = el({ left: 420, right: 480, width: 60, height: 28 }, 'ant-tabs-tab-active')
    const box = container({ left: 0, right: 390, width: 390, height: 36 }, [active])

    scrollActiveTabIntoView(box, 0)

    expect(box.scrollLeft).toBe(90)
  })

  it('无激活项 / 空容器 / 未布局时安全返回', () => {
    const inactive = el({ left: 420, right: 480, width: 60, height: 28 })
    const box = container({ left: 0, right: 390, width: 390, height: 36 }, [inactive])

    expect(() => scrollActiveTabIntoView(box)).not.toThrow()
    expect(box.scrollLeft).toBe(0)
    expect(() => scrollActiveTabIntoView(null)).not.toThrow()

    // 尚未布局（宽高为 0）
    const zero = el({ left: 420, right: 480, width: 0, height: 0 }, 'ant-tabs-tab-active')
    const box2 = container({ left: 0, right: 390, width: 390, height: 36 }, [zero])
    scrollActiveTabIntoView(box2)
    expect(box2.scrollLeft).toBe(0)
  })

  it('同一行存在两级激活项时，以最后一个（二级页签）为滚动目标', () => {
    const wsActive = el({ left: 20, right: 100, width: 80, height: 36 }, 'ant-tabs-tab ant-tabs-tab-active')
    const subActive = el({ left: 560, right: 640, width: 80, height: 32 }, 'cn-table-tab cn-table-tab-active')
    const box = container({ left: 0, right: 390, width: 390, height: 36 }, [wsActive, subActive])

    scrollActiveTabIntoView(box)

    // 二级页签在右侧之外：(640 - 390) + 12
    expect(box.scrollLeft).toBe(262)
  })

  it('nextFrame 包装在下一帧执行并可取消', async () => {
    const active = el({ left: 420, right: 480, width: 60, height: 28 }, 'ant-tabs-tab-active')
    const box = container({ left: 0, right: 390, width: 390, height: 36 }, [active])

    const cancel = scrollActiveTabIntoViewNextFrame(box)
    expect(typeof cancel).toBe('function')
    await new Promise(r => setTimeout(r, 30))
    expect(box.scrollLeft).toBe(102)

    // 取消后不再滚动
    const active2 = el({ left: 420, right: 480, width: 60, height: 28 }, 'ant-tabs-tab-active')
    const box2 = container({ left: 0, right: 390, width: 390, height: 36 }, [active2])
    const cancel2 = scrollActiveTabIntoViewNextFrame(box2)
    cancel2()
    await new Promise(r => setTimeout(r, 30))
    expect(box2.scrollLeft).toBe(0)
  })

  it('无 requestAnimationFrame 时退化为同步执行', () => {
    const original = globalThis.requestAnimationFrame
    // @ts-expect-error 故意置空以覆盖退化分支
    delete globalThis.requestAnimationFrame
    try {
      const active = el({ left: 420, right: 480, width: 60, height: 28 }, 'ant-tabs-tab-active')
      const box = container({ left: 0, right: 390, width: 390, height: 36 }, [active])
      scrollActiveTabIntoViewNextFrame(box)
      expect(box.scrollLeft).toBe(102)
    } finally {
      globalThis.requestAnimationFrame = original
    }
  })
})

describe('scrollActiveTabIntoView 在真实 rAF 下不抛错', () => {
  it('spy rAF 调用次数', () => {
    const spy = vi.spyOn(globalThis, 'requestAnimationFrame')
    const box = container({ left: 0, right: 390, width: 390, height: 36 })
    scrollActiveTabIntoViewNextFrame(box)
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })
})

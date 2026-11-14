/** 并排查看滚动同步测试：进度换算 / 应用 / 容器解析 / 双向监听与生命周期. */

import { describe, expect, it } from 'vitest'
import { useEffect, useRef } from 'react'
import { fireEvent, render } from '@testing-library/react'
import {
  applyScrollProgress,
  findScrollHost,
  scrollProgress,
  useSplitScrollSync,
} from './splitScrollSync'

/** 构造一个「可滚动元素」：jsdom 无布局引擎，滚动尺寸与位置全部用 getter / setter 模拟 */
function makeScrollable(scrollHeight: number, clientHeight: number) {
  const el = document.createElement('div')
  let top = 0
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => clientHeight })
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => top,
    set: (v: number) => {
      top = v
    },
  })
  return el
}

describe('splitScrollSync 纯函数', () => {
  it('滚动进度按可滚动高度归一化并夹在 0..1；无滚动空间为 0', () => {
    expect(scrollProgress({ scrollTop: 0, scrollHeight: 3000, clientHeight: 1000 })).toBe(0)
    expect(scrollProgress({ scrollTop: 1000, scrollHeight: 3000, clientHeight: 1000 })).toBe(0.5)
    expect(scrollProgress({ scrollTop: 2000, scrollHeight: 3000, clientHeight: 1000 })).toBe(1)
    // 内容未超出视口 / 滚动越界回弹：夹紧
    expect(scrollProgress({ scrollTop: 50, scrollHeight: 800, clientHeight: 800 })).toBe(0)
    expect(scrollProgress({ scrollTop: 9999, scrollHeight: 3000, clientHeight: 1000 })).toBe(1)
  })

  it('目标栏按进度换算像素位置；无滚动空间或已就位时不改动（避免回声）', () => {
    const target = makeScrollable(4000, 800) // 可滚动 3200px
    expect(applyScrollProgress(target, 0.5)).toBe(true)
    expect(target.scrollTop).toBe(1600)
    // 同一进度再次应用：已就位，返回 false（不产生新的滚动事件）
    expect(applyScrollProgress(target, 0.5)).toBe(false)
    expect(target.scrollTop).toBe(1600)

    const short = makeScrollable(600, 800)
    expect(applyScrollProgress(short, 1)).toBe(false)
    expect(short.scrollTop).toBe(0)
  })

  it('容器解析：自身可滚动 / 后代可滚动 / 全不可滚动', () => {
    const self = makeScrollable(2000, 600)
    expect(findScrollHost(self)).toBe(self)

    const root = document.createElement('div')
    const inner = makeScrollable(1200, 400)
    root.appendChild(inner)
    expect(findScrollHost(root)).toBe(inner)

    const plain = document.createElement('div')
    plain.appendChild(document.createElement('span'))
    expect(findScrollHost(plain)).toBeNull()
    expect(findScrollHost(null)).toBeNull()
  })
})

function Harness({
  active,
  left,
  right,
}: {
  active: boolean
  left: HTMLElement
  right: HTMLElement
}) {
  const leftRef = useRef<HTMLDivElement>(null)
  const rightRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    leftRef.current?.appendChild(left)
    rightRef.current?.appendChild(right)
  }, [left, right])
  useSplitScrollSync(leftRef, rightRef, active)
  return (
    <div>
      <div data-testid="left-root" ref={leftRef} />
      <div data-testid="right-root" ref={rightRef} />
    </div>
  )
}

describe('useSplitScrollSync 双向同步', () => {
  it('滚动任意一栏，另一栏按同一进度跟随（两栏高度不同）', () => {
    const left = makeScrollable(1600, 600) // 可滚动 1000px
    const right = makeScrollable(4200, 600) // 可滚动 3600px
    render(<Harness active left={left} right={right} />)

    // 左栏滚到 25% → 右栏 900px
    left.scrollTop = 250
    fireEvent.scroll(left)
    expect(right.scrollTop).toBe(900)

    // 右栏滚到 50% → 左栏 500px
    right.scrollTop = 1800
    fireEvent.scroll(right)
    expect(left.scrollTop).toBe(500)
  })

  it('目标栏无可滚动空间时不动（不把另一栏拉回顶部）', () => {
    const left = makeScrollable(3000, 600)
    const right = makeScrollable(600, 600) // 内容未超出视口
    render(<Harness active left={left} right={right} />)

    left.scrollTop = 1200
    fireEvent.scroll(left)
    expect(right.scrollTop).toBe(0)
    expect(left.scrollTop).toBe(1200)
  })

  it('横向滚动（宽表格等无纵向行程的块）不牵动另一栏', () => {
    const left = makeScrollable(1600, 600)
    const right = makeScrollable(4200, 600)
    render(<Harness active left={left} right={right} />)

    // 预览内一个只有横向滚动空间的块：纵向可滚动高度为 0
    const wide = makeScrollable(600, 600)
    Object.defineProperty(wide, 'scrollLeft', { configurable: true, value: 120, writable: true })
    right.appendChild(wide)
    left.scrollTop = 500
    fireEvent.scroll(wide)
    expect(left.scrollTop).toBe(500)
    expect(right.scrollTop).toBe(0)
  })

  it('未激活（单栏 / 窄屏 / 原件族）不监听，卸载后不再响应', () => {
    const left = makeScrollable(1600, 600)
    const right = makeScrollable(4200, 600)
    const { unmount } = render(<Harness active={false} left={left} right={right} />)

    left.scrollTop = 250
    fireEvent.scroll(left)
    expect(right.scrollTop).toBe(0)

    unmount()
    left.scrollTop = 500
    fireEvent.scroll(left)
    expect(right.scrollTop).toBe(0)
  })
})

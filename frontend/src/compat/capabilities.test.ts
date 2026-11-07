/** capabilities 单元测试 —— 旧内核能力探测的唯一入口（ADR 0117 C7） */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isFlexGapSupported, supportsColorMix } from './capabilities'

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

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('supportsColorMix', () => {
  it('CSS.supports 判定通过时返回 true', () => {
    vi.stubGlobal('CSS', { supports: () => true })
    expect(supportsColorMix()).toBe(true)
  })

  it('不支持或环境缺少 CSS 时返回 false', () => {
    vi.stubGlobal('CSS', { supports: () => false })
    expect(supportsColorMix()).toBe(false)
    vi.stubGlobal('CSS', undefined)
    expect(supportsColorMix()).toBe(false)
  })
})

describe('isFlexGapSupported', () => {
  it('按真实布局量出 10px 间距时判定支持', () => {
    mockProbeGap(true)
    expect(isFlexGapSupported()).toBe(true)
  })

  it('grid gap 为真但 flex gap 为假时判定不支持', () => {
    mockProbeGap(false)
    expect(isFlexGapSupported()).toBe(false)
  })

  it('无 document 时按支持处理，避免误装垫片', () => {
    expect(isFlexGapSupported({} as Document)).toBe(true)
  })
})

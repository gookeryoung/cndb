/**
 * exportPdf 模块测试 —— 视图内容导出 PDF.
 *
 * 覆盖：computePageSlices 分页纯函数（整除 / 有余数 / 单页 / 非法输入）；
 * pickOrientation 纸张方向自适应；expandScrollContainers 滚动容器展开与恢复；
 * exportViewToPdf 编排（html2canvas / jsPDF 均为 mock，jsdom 无真实 canvas）：
 * 纵横向自适应、多页时 addPage 调用次数与 addImage 次数一致、save 收到文件名、
 * 展开状态在渲染期生效并在渲染后还原。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { computePageSlices, expandScrollContainers, exportViewToPdf, measureContentBounds, pickOrientation } from './exportPdf'

/** hoisted mock：jsdom 无真实 canvas 渲染，html2canvas / jsPDF 均替换为桩 */
const html2canvasMock = vi.hoisted(() => vi.fn())
const jsPDFMock = vi.hoisted(() => vi.fn())

vi.mock('html2canvas-pro', () => ({ default: html2canvasMock }))
vi.mock('jspdf', () => ({ jsPDF: jsPDFMock }))

describe('computePageSlices 分页切片', () => {
  it('内容高度不足一页时输出单页切片', () => {
    expect(computePageSlices(500, 785)).toEqual([{ y: 0, height: 500 }])
  })

  it('恰好整除时均分为多页且不产生空尾页', () => {
    expect(computePageSlices(1600, 800)).toEqual([
      { y: 0, height: 800 },
      { y: 800, height: 800 },
    ])
  })

  it('有余数时末页为剩余高度', () => {
    expect(computePageSlices(2000, 785.19)).toEqual([
      { y: 0, height: 785.19 },
      { y: expect.closeTo(785.19, 6), height: expect.closeTo(785.19, 6) },
      { y: expect.closeTo(1570.38, 6), height: expect.closeTo(429.62, 6) },
    ])
  })

  it('非法输入（非有限数 / 非正数）返回空数组', () => {
    expect(computePageSlices(0, 785)).toEqual([])
    expect(computePageSlices(-1, 785)).toEqual([])
    expect(computePageSlices(100, 0)).toEqual([])
    expect(computePageSlices(NaN, 785)).toEqual([])
    expect(computePageSlices(Infinity, 785)).toEqual([])
  })
})

describe('pickOrientation 纸张方向自适应', () => {
  it('内容宽 > 高用横版（landscape）', () => {
    expect(pickOrientation(2000, 800)).toBe('landscape')
  })

  it('内容高 >= 宽用竖版（portrait）', () => {
    expect(pickOrientation(800, 2000)).toBe('portrait')
    expect(pickOrientation(1000, 1000)).toBe('portrait')
  })
})

describe('expandScrollContainers 滚动容器展开与恢复', () => {
  it('auto/scroll 容器两轴放开为 visible，恢复函数还原原内联值', () => {
    const target = document.createElement('div')
    const scroller = document.createElement('div')
    scroller.style.overflowY = 'auto'
    const hiddenText = document.createElement('span')
    hiddenText.style.overflow = 'hidden'
    hiddenText.style.textOverflow = 'ellipsis'
    target.append(scroller, hiddenText)

    const restore = expandScrollContainers(target)
    // 真实滚动容器两轴全部放开（visible+非 visible 组合会被强制按 auto 计算）
    expect(scroller.style.overflowX).toBe('visible')
    expect(scroller.style.overflowY).toBe('visible')
    // overflow:hidden 的文本 ellipsis 容器不受影响
    expect(hiddenText.style.overflow).toBe('hidden')

    restore()
    expect(scroller.style.overflowY).toBe('auto')
    expect(scroller.style.overflowX).toBe('')
  })

  it('非零滚动偏移被清零并在恢复时还原（同步裁剪容器归位）', () => {
    const target = document.createElement('div')
    const scrolled = document.createElement('div')
    target.appendChild(scrolled)
    scrolled.scrollLeft = 120
    scrolled.scrollTop = 40

    const restore = expandScrollContainers(target)
    expect(scrolled.scrollLeft).toBe(0)
    expect(scrolled.scrollTop).toBe(0)

    restore()
    expect(scrolled.scrollLeft).toBe(120)
    expect(scrolled.scrollTop).toBe(40)
  })
})

describe('measureContentBounds 包围盒测量', () => {
  it('取目标与全部后代包围盒的并集（溢出目标框的部分计入）', () => {
    const target = document.createElement('div')
    const wideChild = document.createElement('div')
    const tallChild = document.createElement('div')
    target.append(wideChild, tallChild)

    const rects = new Map<Element, DOMRect>([
      [target, new DOMRect(10, 20, 400, 300)],
      [wideChild, new DOMRect(10, 20, 1600, 100)],
      [tallChild, new DOMRect(10, 20, 100, 1200)],
    ])
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      return rects.get(this) ?? new DOMRect(0, 0, 0, 0)
    })

    const bounds = measureContentBounds(target)
    expect(bounds.width).toBeCloseTo(1600)
    expect(bounds.height).toBeCloseTo(1200)
  })
})

describe('exportViewToPdf 编排（库已 mock）', () => {
  /** 模拟源 canvas：宽 1077.16px（pxPerPt=2），高 4000px → 竖版，缩放后内容高 2000pt → 3 页 */
  const fakeCanvas = { width: 1077.16, height: 4000 }
  /** 模拟横版内容：宽 4000px，高 1077.16px → 横版单页 */
  const wideCanvas = { width: 4000, height: 1077.16 }

  /** 构造 jsPDF 实例桩：页面尺寸按构造参数 orientation 返回（A4 两向） */
  const makePdfInstance = () => ({
    internal: {
      pageSize: {
        getWidth: () => (orientationUsed === 'landscape' ? 841.89 : 595.28),
        getHeight: () => (orientationUsed === 'landscape' ? 595.28 : 841.89),
      },
    },
    addPage: vi.fn(),
    addImage: vi.fn(),
    save: vi.fn(),
  })
  let orientationUsed: string
  let pdfInstance: ReturnType<typeof makePdfInstance>

  beforeEach(() => {
    vi.clearAllMocks()
    orientationUsed = 'portrait'
    pdfInstance = makePdfInstance()
    html2canvasMock.mockResolvedValue(fakeCanvas)
    // 普通函数实现：需支持 new jsPDF(...) 调用（箭头函数不可构造）
    jsPDFMock.mockImplementation(function (opts?: { orientation?: string }) {
      orientationUsed = opts?.orientation ?? 'portrait'
      return pdfInstance
    })
    // jsdom 无 canvas 实现：拦截 createElement('canvas') 返回带 stub 2d 上下文的伪 canvas
    const realCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      if (tag === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ({ fillRect: vi.fn(), drawImage: vi.fn() }),
          toDataURL: () => 'data:image/jpeg;base64,fake',
        } as unknown as HTMLCanvasElement
      }
      return realCreateElement(tag)
    }) as typeof document.createElement)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('超高内容竖版分页：addPage 比页数少 1，addImage 与 save 各按页数/一次调用', async () => {
    const target = document.createElement('div')
    await exportViewToPdf(target, 'view-测试-20260101_120000.pdf')

    expect(jsPDFMock).toHaveBeenCalledWith(expect.objectContaining({ orientation: 'portrait' }))
    // 内容高 2000pt，每页内容区 841.89 - 2*28.35 = 785.19pt → 3 页
    expect(pdfInstance.addPage).toHaveBeenCalledTimes(2)
    expect(pdfInstance.addImage).toHaveBeenCalledTimes(3)
    // 每页宽度均为内容区宽度 595.28 - 56.7 = 538.58pt
    for (const call of pdfInstance.addImage.mock.calls) {
      expect(call[4]).toBeCloseTo(538.58, 2)
    }
    expect(pdfInstance.save).toHaveBeenCalledWith('view-测试-20260101_120000.pdf')
  })

  it('宽内容自动用横版：jsPDF 收到 landscape，内容区宽度放大到 785.19pt 且单页', async () => {
    html2canvasMock.mockResolvedValue(wideCanvas)
    const target = document.createElement('div')
    await exportViewToPdf(target, 'view-宽看板.pdf')

    expect(jsPDFMock).toHaveBeenCalledWith(expect.objectContaining({ orientation: 'landscape' }))
    // 横版内容区宽 841.89 - 56.7 = 785.19pt；pxPerPt = 4000/785.19 ≈ 5.094，
    // 缩放后内容高 1077.16/pxPerPt ≈ 211.4pt，不足一页 → 单页
    expect(pdfInstance.addPage).not.toHaveBeenCalled()
    expect(pdfInstance.addImage).toHaveBeenCalledTimes(1)
    expect(pdfInstance.addImage.mock.calls[0][4]).toBeCloseTo(785.19, 2)
  })

  it('渲染期滚动容器处于展开状态，渲染完成后还原', async () => {
    const target = document.createElement('div')
    const scroller = document.createElement('div')
    scroller.style.overflowY = 'auto'
    target.appendChild(scroller)
    // 在 html2canvas 调用时断言展开状态已生效
    html2canvasMock.mockImplementation(async () => {
      expect(scroller.style.overflowY).toBe('visible')
      return fakeCanvas
    })

    await exportViewToPdf(target, 'a.pdf')
    // 渲染完成后立即还原，不阻塞后续 PDF 切片
    expect(scroller.style.overflowY).toBe('auto')
  })

  it('渲染失败时向上抛出原始错误且还原展开状态', async () => {
    const target = document.createElement('div')
    const scroller = document.createElement('div')
    scroller.style.overflowY = 'auto'
    target.appendChild(scroller)
    html2canvasMock.mockRejectedValue(new Error('渲染崩溃'))
    await expect(exportViewToPdf(target, 'a.pdf')).rejects.toThrow('渲染崩溃')
    expect(scroller.style.overflowY).toBe('auto')
  })
})

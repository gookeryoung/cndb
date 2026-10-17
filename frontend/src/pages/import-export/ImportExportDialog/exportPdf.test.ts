/**
 * exportPdf 模块测试 —— 视图内容导出 PDF.
 *
 * 覆盖：pickOrientation 方向判定；computePageSize 页面自适应（宽内容扩页 / 窄内容保持 A4 /
 * 超上限钳制）；computeRenderScale 目标 DPI 反算与像素预算压制；
 * expandScrollContainers 滚动容器展开与恢复；measureContentBounds 包围盒测量；
 * exportViewToPdf 编排（html2canvas / jsPDF 均为 mock，jsdom 无真实 canvas）：
 * 1:1 排版尺寸、窄内容居中、超单页上限才分页、JPEG 质量与平滑参数、
 * save 收到文件名、展开状态在渲染期生效并在渲染后还原。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  A4_PAGE_PT,
  CSS_DPI,
  MAX_PAGE_PT,
  MAX_RENDER_SCALE,
  MIN_RENDER_SCALE,
  PAGE_MARGIN_PT,
  PDF_IMAGE_QUALITY,
  PX_TO_PT,
  TARGET_RENDER_DPI,
  computePageSize,
  computeRenderScale,
  expandScrollContainers,
  exportViewToPdf,
  measureContentBounds,
  pickOrientation,
} from './exportPdf'

/** hoisted mock：jsdom 无真实 canvas 渲染，html2canvas / jsPDF 均替换为桩 */
const html2canvasMock = vi.hoisted(() => vi.fn())
const jsPDFMock = vi.hoisted(() => vi.fn())
/** 记录 pageCanvas.toDataURL 的实参，用于断言编码格式与 JPEG 质量 */
const toDataURLMock = vi.hoisted(() => vi.fn(() => 'data:image/jpeg;base64,fake'))

vi.mock('html2canvas-pro', () => ({ default: html2canvasMock }))
vi.mock('jspdf', () => ({ jsPDF: jsPDFMock }))

describe('pickOrientation 纸张方向自适应', () => {
  it('内容宽 > 高用横版（landscape）', () => {
    expect(pickOrientation(2000, 800)).toBe('landscape')
  })

  it('内容高 >= 宽用竖版（portrait）', () => {
    expect(pickOrientation(800, 2000)).toBe('portrait')
    expect(pickOrientation(1000, 1000)).toBe('portrait')
  })
})

describe('computePageSize 页面尺寸自适应', () => {
  it('宽内容按 1:1 撑大页面，而不是把内容压进 A4 宽度', () => {
    // 1390x900 CSS px 的看板 → 1042.5x675pt
    const size = computePageSize(1390 * PX_TO_PT, 900 * PX_TO_PT)
    expect(size.width).toBeCloseTo(1390 * PX_TO_PT + PAGE_MARGIN_PT * 2, 6)
    expect(size.height).toBeCloseTo(900 * PX_TO_PT + PAGE_MARGIN_PT * 2, 6)
    // 页面内容区恰好等于内容物理尺寸 → 1:1 落纸，无缩放
    expect(size.width - PAGE_MARGIN_PT * 2).toBeCloseTo(1390 * PX_TO_PT, 6)
  })

  it('窄内容仍用 A4 基准（不会缩成小纸），横版取长边为宽', () => {
    expect(computePageSize(600 * PX_TO_PT, 400 * PX_TO_PT)).toEqual({
      width: A4_PAGE_PT.height,
      height: A4_PAGE_PT.width,
    })
  })

  it('高内容用竖版基准，超出时按内容加高', () => {
    const size = computePageSize(600 * PX_TO_PT, 1200 * PX_TO_PT)
    expect(size.width).toBe(A4_PAGE_PT.width)
    expect(size.height).toBeCloseTo(1200 * PX_TO_PT + PAGE_MARGIN_PT * 2, 6)
  })

  it('超出 PDF 单页上限时钳到 MAX_PAGE_PT（由调用方改多页平铺）', () => {
    const size = computePageSize(40_000, 40_000)
    expect(size.width).toBe(MAX_PAGE_PT)
    expect(size.height).toBe(MAX_PAGE_PT)
  })
})

describe('computeRenderScale 渲染分辨率反算', () => {
  it('1:1 排版下恒按目标 DPI 取 300/96 ≈ 3.125，与内容尺寸无关', () => {
    const expected = TARGET_RENDER_DPI / CSS_DPI
    expect(computeRenderScale(1390, 900)).toBeCloseTo(expected, 6)
    expect(computeRenderScale(600, 400)).toBeCloseTo(expected, 6)
    // 旧实现固定 scale:2 → 仅 192~255 DPI
    expect(computeRenderScale(1390, 900)).toBeGreaterThan(2)
  })

  it('超大内容受像素预算压制，但不低于 MIN_RENDER_SCALE 之外的兜底 1', () => {
    expect(computeRenderScale(4000, 3000)).toBeGreaterThan(1)
    expect(computeRenderScale(4000, 3000)).toBeLessThan(MIN_RENDER_SCALE)
    expect(computeRenderScale(12_000, 9000)).toBe(1)
  })

  it('缩放系数不超过 MAX_RENDER_SCALE', () => {
    expect(computeRenderScale(100, 100)).toBeLessThanOrEqual(MAX_RENDER_SCALE)
  })

  it('非法尺寸回退到 MIN_RENDER_SCALE', () => {
    expect(computeRenderScale(0, 900)).toBe(MIN_RENDER_SCALE)
    expect(computeRenderScale(1390, 0)).toBe(MIN_RENDER_SCALE)
    expect(computeRenderScale(NaN, 900)).toBe(MIN_RENDER_SCALE)
    expect(computeRenderScale(Infinity, 900)).toBe(MIN_RENDER_SCALE)
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
  /** 宽看板内容：2780x1800px @scale2 → 1042.5x675pt（正好 A4 装不下 → 扩页单页） */
  const boardCanvas = { width: 2780, height: 1800 }
  /** 窄内容：800x600px @scale2 → 300x225pt（A4 装得下 → 居中） */
  const narrowCanvas = { width: 800, height: 600 }
  /** 超高内容：height 使内容高达 15000pt > MAX_PAGE_PT → 被迫分页 */
  const hugeCanvas = { width: 2780, height: 40_000 }

  /** 构造 jsPDF 实例桩：页尺寸取自构造参数 format（与真实 jsPDF 的自定义页面一致） */
  const makePdfInstance = (format: [number, number]) => ({
    internal: {
      pageSize: {
        getWidth: () => format[0],
        getHeight: () => format[1],
      },
    },
    addPage: vi.fn(),
    addImage: vi.fn(),
    save: vi.fn(),
  })
  let jsPDFOptions: { format: [number, number]; orientation: string; unit: string } | undefined
  let pdfInstance: ReturnType<typeof makePdfInstance>

  beforeEach(() => {
    vi.clearAllMocks()
    pdfInstance = makePdfInstance([A4_PAGE_PT.width, A4_PAGE_PT.height])
    html2canvasMock.mockResolvedValue(boardCanvas)
    // 普通函数实现：需支持 new jsPDF(...) 调用（箭头函数不可构造）
    jsPDFMock.mockImplementation(function (opts: { format: [number, number]; orientation: string; unit: string }) {
      jsPDFOptions = opts
      pdfInstance = makePdfInstance(opts.format)
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
          toDataURL: toDataURLMock,
        } as unknown as HTMLCanvasElement
      }
      return realCreateElement(tag)
    }) as typeof document.createElement)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('宽看板按 1:1 出图：页面撑到内容大小、单页、图像尺寸等于内容物理尺寸', async () => {
    const target = document.createElement('div')
    await exportViewToPdf(target, 'view-测试-20260101_120000.pdf')

    const contentWidthPt = 2780 / MIN_RENDER_SCALE * PX_TO_PT
    const contentHeightPt = 1800 / MIN_RENDER_SCALE * PX_TO_PT
    // jsPDF 必须用横版自定义页（宽 > 高时传 portrait 会被 jsPDF 交换宽高）
    expect(jsPDFOptions?.orientation).toBe('landscape')
    expect(jsPDFOptions?.format[0]).toBeCloseTo(contentWidthPt + PAGE_MARGIN_PT * 2, 6)
    expect(jsPDFOptions?.format[1]).toBeCloseTo(contentHeightPt + PAGE_MARGIN_PT * 2, 6)

    expect(pdfInstance.addPage).not.toHaveBeenCalled()
    expect(pdfInstance.addImage).toHaveBeenCalledTimes(1)
    const [, , x, y, w, h] = pdfInstance.addImage.mock.calls[0]
    expect(x).toBeCloseTo(PAGE_MARGIN_PT, 6)
    expect(y).toBeCloseTo(PAGE_MARGIN_PT, 6)
    // 内容不再被压缩：落纸宽度 = 内容物理宽度（旧实现会被压到 785.19pt）
    expect(w).toBeCloseTo(contentWidthPt, 6)
    expect(h).toBeCloseTo(contentHeightPt, 6)
    expect(pdfInstance.save).toHaveBeenCalledWith('view-测试-20260101_120000.pdf')
  })

  it('窄内容保持 A4 横版并在页内居中，不做放大', async () => {
    html2canvasMock.mockResolvedValue(narrowCanvas)
    const target = document.createElement('div')
    await exportViewToPdf(target, 'view-窄.pdf')

    expect(jsPDFOptions?.orientation).toBe('landscape')
    expect(jsPDFOptions?.format).toEqual([A4_PAGE_PT.height, A4_PAGE_PT.width])

    const [, , x, y, w, h] = pdfInstance.addImage.mock.calls[0]
    const contentWidthPt = 800 / MIN_RENDER_SCALE * PX_TO_PT
    const contentHeightPt = 600 / MIN_RENDER_SCALE * PX_TO_PT
    expect(w).toBeCloseTo(contentWidthPt, 6)
    expect(h).toBeCloseTo(contentHeightPt, 6)
    expect(x).toBeCloseTo(PAGE_MARGIN_PT + (A4_PAGE_PT.height - PAGE_MARGIN_PT * 2 - contentWidthPt) / 2, 6)
    expect(y).toBeCloseTo(PAGE_MARGIN_PT + (A4_PAGE_PT.width - PAGE_MARGIN_PT * 2 - contentHeightPt) / 2, 6)
    expect(pdfInstance.addImage).toHaveBeenCalledTimes(1)
  })

  it('内容超过单页上限才分页：addPage 比页数少 1，末页只占剩余高度', async () => {
    html2canvasMock.mockResolvedValue(hugeCanvas)
    const target = document.createElement('div')
    await exportViewToPdf(target, 'view-超高.pdf')

    const contentHeightPt = 40_000 / MIN_RENDER_SCALE * PX_TO_PT // 15000pt
    const availHeightPt = MAX_PAGE_PT - PAGE_MARGIN_PT * 2
    expect(jsPDFOptions?.format[1]).toBe(MAX_PAGE_PT)

    expect(pdfInstance.addPage).toHaveBeenCalledTimes(1)
    expect(pdfInstance.addImage).toHaveBeenCalledTimes(2)
    expect(pdfInstance.addImage.mock.calls[0][5]).toBeCloseTo(availHeightPt, 6)
    expect(pdfInstance.addImage.mock.calls[1][5]).toBeCloseTo(contentHeightPt - availHeightPt, 6)
  })

  it('渲染期滚动容器处于展开状态，渲染完成后还原', async () => {
    const target = document.createElement('div')
    const scroller = document.createElement('div')
    scroller.style.overflowY = 'auto'
    target.appendChild(scroller)
    // 在 html2canvas 调用时断言展开状态已生效
    html2canvasMock.mockImplementation(async () => {
      expect(scroller.style.overflowY).toBe('visible')
      return boardCanvas
    })

    await exportViewToPdf(target, 'a.pdf')
    // 渲染完成后立即还原，不阻塞后续 PDF 切片
    expect(scroller.style.overflowY).toBe('auto')
  })

  it('按目标 DPI 反算 scale 并开启高平滑；页面位图用高质 JPEG 写入', async () => {
    // jsdom 的 getBoundingClientRect 恒为 0 → 包围盒非法，回退到 MIN_RENDER_SCALE
    const target = document.createElement('div')
    await exportViewToPdf(target, 'a.pdf')

    expect(html2canvasMock).toHaveBeenCalledWith(
      target,
      expect.objectContaining({ scale: MIN_RENDER_SCALE, imageSmoothingQuality: 'high' }),
    )
    expect(toDataURLMock).toHaveBeenCalledWith('image/jpeg', PDF_IMAGE_QUALITY)
    // 单页只编码一次
    expect(toDataURLMock).toHaveBeenCalledTimes(1)
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

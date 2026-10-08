/**
 * exportPdf 模块测试 —— 视图内容导出 PDF.
 *
 * 覆盖：computePageSlices 分页纯函数（整除 / 有余数 / 单页 / 非法输入）；
 * exportViewToPdf 编排（html2canvas / jsPDF 均为 mock，jsdom 无真实 canvas）：
 * 多页时 addPage 调用次数与 addImage 次数一致、save 收到文件名。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { computePageSlices, exportViewToPdf } from './exportPdf'

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

describe('exportViewToPdf 编排（库已 mock）', () => {
  /** 模拟源 canvas：宽 1077.16px（pxPerPt=2），高 4000px → 缩放后内容高 2000pt → 3 页 */
  const fakeCanvas = {
    width: 1077.16,
    height: 4000,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    html2canvasMock.mockResolvedValue(fakeCanvas)
    const pdfInstance = {
      internal: { pageSize: { getWidth: () => 595.28, getHeight: () => 841.89 } },
      addPage: vi.fn(),
      addImage: vi.fn(),
      save: vi.fn(),
    }
    // 普通函数实现：需支持 new jsPDF(...) 调用（箭头函数不可构造）
    jsPDFMock.mockImplementation(function () { return pdfInstance })
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

  it('超高内容正确分页：addPage 比页数少 1，addImage 与 save 各按页数/一次调用', async () => {
    const target = document.createElement('div')
    await exportViewToPdf(target, 'view-测试-20260101_120000.pdf')

    // 内容高 2000pt，每页内容区 841.89 - 2*28.35 = 785.19pt → 3 页
    const instance = jsPDFMock.mock.results[0].value
    expect(instance.addPage).toHaveBeenCalledTimes(2)
    expect(instance.addImage).toHaveBeenCalledTimes(3)
    // 每页宽度均为内容区宽度 595.28 - 56.7 = 538.58pt
    for (const call of instance.addImage.mock.calls) {
      expect(call[4]).toBeCloseTo(538.58, 2)
    }
    expect(instance.save).toHaveBeenCalledWith('view-测试-20260101_120000.pdf')
  })

  it('渲染失败时向上抛出原始错误', async () => {
    html2canvasMock.mockRejectedValue(new Error('渲染崩溃'))
    await expect(exportViewToPdf(document.createElement('div'), 'a.pdf')).rejects.toThrow('渲染崩溃')
  })
})

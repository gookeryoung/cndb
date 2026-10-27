/** chartImageSave 单测：文件名清洗 / SVG 下载 / 栅格化降级。 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { downloadChartSvg, saveChartImage } from './chartImageSave'

const SVG = '<svg width="320" height="200"><rect width="320" height="200" fill="#fff"/></svg>'

describe('chartImageSave', () => {
  let clicked: string[]
  let blobOf: (index: number) => Blob | undefined
  let createdUrls: string[]
  let revokeSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    clicked = []
    createdUrls = []
    const blobs: Blob[] = []
    blobOf = index => blobs[index - 1]
    revokeSpy = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn((blob: Blob) => {
        blobs.push(blob)
        createdUrls.push(blob.type)
        return `blob:mock-${blobs.length}`
      }),
      revokeObjectURL: revokeSpy,
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('download') ?? '')
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('downloadChartSvg 下载 SVG 并释放 URL', async () => {
    downloadChartSvg(SVG, '趋势图.svg')
    expect(createdUrls).toEqual(['image/svg+xml;charset=utf-8'])
    expect(clicked).toEqual(['趋势图.svg'])
    expect(await blobOf(1)!.text()).toContain('<rect')
    expect(revokeSpy).toHaveBeenCalledWith('blob:mock-1')
  })

  it('downloadChartSvg 为缺 xmlns 的 SVG 补命名空间', () => {
    downloadChartSvg(SVG.replace('<svg ', '<svg data-x="1" '), 'a.svg')
    expect(clicked).toEqual(['a.svg'])
  })

  it('saveChartImage 空内容返回 false 不触发下载', async () => {
    expect(await saveChartImage('', 'png', '图')).toBe(false)
    expect(clicked).toHaveLength(0)
  })

  it('saveChartImage(png)：2x 栅格化 + JPEG 垫白底 + 文件名清洗', async () => {
    vi.stubGlobal('Image', class {
      onload: () => void = () => {}
      constructor() { queueMicrotask(() => this.onload()) }
    })
    const drawImage = vi.fn()
    const fillRect = vi.fn()
    const toDataURL = vi.fn(() => 'data:image/png;base64,xxx')
    const canvasMock = {
      width: 0,
      height: 0,
      getContext: () => ({ fillStyle: '', fillRect, drawImage }),
      toDataURL,
    }
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) =>
      tag === 'canvas' ? canvasMock : realCreate(tag)) as typeof document.createElement)

    expect(await saveChartImage(SVG, 'png', 'A/B:C*?')).toBe(true)
    expect(clicked).toEqual(['A_B_C__.png'])
    expect(canvasMock.width).toBe(640)
    expect(canvasMock.height).toBe(400)
    expect(drawImage).toHaveBeenCalledTimes(1)
    expect(fillRect).not.toHaveBeenCalled()

    // JPEG：先垫白底再绘制
    expect(await saveChartImage(SVG, 'jpeg', '')).toBe(true)
    expect(clicked[1]).toBe('图表.jpg')
    expect(fillRect).toHaveBeenCalledTimes(1)
  })

  it('rasterize 加载失败时 saveChartImage 返回 false 不触发下载', async () => {
    vi.stubGlobal('Image', class {
      onerror: () => void = () => {}
      constructor() { queueMicrotask(() => this.onerror()) }
    })
    expect(await saveChartImage(SVG, 'jpeg', '图')).toBe(false)
    expect(clicked).toHaveLength(0)
  })
})

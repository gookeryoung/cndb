/** exportPng 模块测试 —— 与 PDF 共用的视觉快照链路只负责 PNG 编码与下载（ADR 0023 / 原 0077 P0）.
 *
 * 捕获本身由 `exportPdf.captureElement` 覆盖，这里只验证：背景色透传、下载链接生命周期、
 * 空画面报错、捕获异常透传。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { exportElementToPng } from './exportPng'

const captureMock = vi.hoisted(() => ({ captureElement: vi.fn() }))
vi.mock('./exportPdf', () => ({ captureElement: captureMock.captureElement }))

const toDataURLMock = vi.hoisted(() => vi.fn(() => 'data:image/png;base64,fake'))

describe('exportElementToPng', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    captureMock.captureElement.mockResolvedValue({
      canvas: { toDataURL: toDataURLMock },
      renderScale: 2,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('用 PNG 编码触发下载，并把背景色传给捕获', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const target = document.createElement('div')

    await exportElementToPng(target, '画布-20260101_120000.png', '#141414')

    expect(captureMock.captureElement).toHaveBeenCalledWith(target, '#141414')
    expect(toDataURLMock).toHaveBeenCalledWith('image/png')
    expect(click).toHaveBeenCalledTimes(1)
    const link = click.mock.instances[0] as HTMLAnchorElement
    expect(link.download).toBe('画布-20260101_120000.png')
    expect(link.href).toBe('data:image/png;base64,fake')
    // 下载后立即从文档移除临时链接
    expect(document.body.contains(link)).toBe(false)
  })

  it('默认背景为白色（与既有 PDF 口径一致）', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const target = document.createElement('div')
    await exportElementToPng(target, 'a.png')
    expect(captureMock.captureElement).toHaveBeenCalledWith(target, '#ffffff')
  })

  it('画面为空时抛错而不是下载空文件', async () => {
    toDataURLMock.mockReturnValueOnce('data:,')
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const target = document.createElement('div')
    await expect(exportElementToPng(target, 'a.png')).rejects.toThrow('PNG 导出失败')
  })

  it('捕获失败时向上抛出原始错误', async () => {
    captureMock.captureElement.mockRejectedValueOnce(new Error('渲染崩溃'))
    const target = document.createElement('div')
    await expect(exportElementToPng(target, 'a.png')).rejects.toThrow('渲染崩溃')
  })
})

/** ADR 0129 P1：PPTX 服务端 PDF 预览状态机单测. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { documentsApi } from '@/api/documents'
import {
  fetchPptxPdf,
  PPTX_PDF_MAX_WAIT_MS,
  PPTX_PDF_RETRY_DELAYS_MS,
  requestPptxPdf,
  stateFromStatus,
} from './pptxPdf'

const PDF_BLOB = new Blob(['%PDF-1.7'], { type: 'application/pdf' })

afterEach(() => {
  vi.restoreAllMocks()
})

describe('stateFromStatus', () => {
  it.each([
    [200, 'ready'],
    [202, 'pending'],
    [409, 'disabled'],
    [413, 'too_large'],
    [422, 'failed'],
    [503, 'busy'],
  ] as const)('HTTP %s → %s', (status, expected) => {
    expect(stateFromStatus(status)).toBe(expected)
  })

  it('未知状态按失败处理（保留客户端预览）', () => {
    expect(stateFromStatus(418)).toBe('failed')
  })
})

describe('fetchPptxPdf', () => {
  it('200 直接返回 PDF blob', async () => {
    const spy = vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status: 200, data: PDF_BLOB })

    await expect(fetchPptxPdf(7, 31)).resolves.toEqual({ state: 'ready', blob: PDF_BLOB })
    expect(spy).toHaveBeenCalledWith(7, 31, undefined)
  })

  it('202 按退避轮询，直到 200', async () => {
    const spy = vi
      .spyOn(documentsApi, 'assetPdf')
      .mockResolvedValueOnce({ status: 202, data: null })
      .mockResolvedValueOnce({ status: 202, data: null })
      .mockResolvedValueOnce({ status: 200, data: PDF_BLOB })

    const result = await fetchPptxPdf(7, 31, { delays: [1, 1] })

    expect(result.state).toBe('ready')
    expect(spy).toHaveBeenCalledTimes(3)
  })

  it.each([409, 413, 422, 503] as const)('HTTP %s 不再轮询，直接返回不可用状态', async status => {
    const spy = vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status, data: null })

    const result = await fetchPptxPdf(7, 31, { delays: [1] })

    expect(result.state).toBe(stateFromStatus(status))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('200 但缺少 blob 时按失败降级', async () => {
    vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status: 200, data: null })
    await expect(fetchPptxPdf(7, 31)).resolves.toEqual({ state: 'failed' })
  })

  it('超过等待预算后保持 pending，不再继续请求', async () => {
    const spy = vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status: 202, data: null })

    const result = await fetchPptxPdf(7, 31, { delays: [10], maxWaitMs: 5 })

    expect(result).toEqual({ state: 'pending' })
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('AbortSignal 触发后停止轮询并抛出 AbortError（组件卸载）', async () => {
    const spy = vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status: 202, data: null })
    const controller = new AbortController()

    const promise = fetchPptxPdf(7, 31, { signal: controller.signal, delays: [50], maxWaitMs: 10_000 })
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    controller.abort()

    await expect(promise).rejects.toThrow(/aborted/)
    expect(spy).toHaveBeenCalledTimes(1)
  })
})

describe('requestPptxPdf', () => {
  it('POST 200 表示已就绪', async () => {
    const spy = vi.spyOn(documentsApi, 'requestAssetPdf').mockResolvedValue({ status: 200 })
    await expect(requestPptxPdf(7, 31)).resolves.toBe('ready')
    expect(spy).toHaveBeenCalledWith(7, 31)
  })

  it('POST 202 表示重新进入转换', async () => {
    vi.spyOn(documentsApi, 'requestAssetPdf').mockResolvedValue({ status: 202 })
    await expect(requestPptxPdf(7, 31)).resolves.toBe('pending')
  })
})

describe('轮询参数', () => {
  it('退避与预算符合 ADR 0129 §6', () => {
    expect(PPTX_PDF_RETRY_DELAYS_MS).toEqual([2000, 3000, 5000])
    expect(PPTX_PDF_MAX_WAIT_MS).toBe(60_000)
  })
})

/** PPTX 悬停预取：非 PPTX / 慢网跳过、失败静默、防抖只保留最后一次. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { waitFor } from '@testing-library/react'
import { documentsApi, type DocumentItem } from '@/api/documents'
import { createPptxPrefetcher, prefetchPptxPreview } from './pptxPrefetch'
import { PPTX_MIME } from './pptxLoader'

vi.mock('./pptxLoader', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./pptxLoader')>()
  return {
    ...actual,
    // 预取单测不加载真实渲染库，只验证查询 / 防抖调度
    loadPptxModule: vi.fn(() => Promise.resolve({} as typeof import('pptx-preview'))),
  }
})

const PPTX_DOC = { id: 9, content_type: 'pptx', asset_mime: PPTX_MIME } as DocumentItem

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

beforeEach(() => {
  vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['PK']))
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  delete (navigator as Navigator & { connection?: unknown }).connection
})

describe('prefetchPptxPreview', () => {
  it('非 PPTX 文档不预取', () => {
    const assetBlob = vi.mocked(documentsApi.assetBlob)
    prefetchPptxPreview(makeClient(), 10, {
      ...PPTX_DOC, content_type: 'pdf', asset_mime: 'application/pdf',
    })

    expect(assetBlob).not.toHaveBeenCalled()
  })

  it('PPTX 文档预取渲染库与原件，失败静默', async () => {
    const assetBlob = vi.mocked(documentsApi.assetBlob)
    assetBlob.mockRejectedValueOnce(new Error('offline'))
    expect(() => prefetchPptxPreview(makeClient(), 10, PPTX_DOC)).not.toThrow()
    await waitFor(() => expect(assetBlob).toHaveBeenCalledWith(10, 9))
  })

  it('saveData 慢网不预取', () => {
    Object.defineProperty(navigator, 'connection', { configurable: true, value: { saveData: true } })
    const assetBlob = vi.mocked(documentsApi.assetBlob)
    prefetchPptxPreview(makeClient(), 10, PPTX_DOC)

    expect(assetBlob).not.toHaveBeenCalled()
  })
})

describe('createPptxPrefetcher', () => {
  it('防抖窗口内只执行最后一次，取消后不再执行', () => {
    vi.useFakeTimers()
    const prefetch = vi.fn()
    const scheduler = createPptxPrefetcher(prefetch, 200)
    const first = { ...PPTX_DOC, id: 1 }
    const second = { ...PPTX_DOC, id: 2 }

    scheduler.schedule(first)
    vi.advanceTimersByTime(150)
    scheduler.schedule(second)
    vi.advanceTimersByTime(199)
    expect(prefetch).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(prefetch).toHaveBeenCalledTimes(1)
    expect(prefetch).toHaveBeenCalledWith(second)

    scheduler.schedule(first)
    scheduler.cancel()
    vi.advanceTimersByTime(500)
    expect(prefetch).toHaveBeenCalledTimes(1)
  })
})

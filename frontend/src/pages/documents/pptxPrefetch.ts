/** PPTX 列表悬停预取：防抖后预取渲染库 chunk 与原件 blob，不改变页面错误态.
 *
 * 只在桌面端悬停触发；`saveData` / 2G 等慢网直接跳过，扫过列表不产生请求风暴。
 */

import type { QueryClient } from '@tanstack/react-query'
import { documentsApi, type DocumentItem } from '@/api/documents'
import {
  isPreviewablePptx, loadPptxModule, PPTX_ASSET_GC_MS, PPTX_ASSET_STALE_MS,
} from './pptxLoader'

export const PPTX_PREFETCH_DELAY_MS = 220

type NetworkInformation = {
  saveData?: boolean
  effectiveType?: string
}

function shouldSkipPrefetch() {
  if (typeof navigator === 'undefined' || navigator.onLine === false) return true
  const connection = (navigator as Navigator & { connection?: NetworkInformation }).connection
  return Boolean(
    connection?.saveData || ['slow-2g', '2g'].includes(connection?.effectiveType ?? ''),
  )
}

/** 预取失败静默：悬停只是加速，失败不影响点击后的正常加载与错误提示 */
export function prefetchPptxPreview(
  queryClient: QueryClient,
  workspaceId: number,
  doc: DocumentItem,
) {
  if (!isPreviewablePptx(doc) || shouldSkipPrefetch()) return
  void loadPptxModule().catch(() => undefined)
  void queryClient.prefetchQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset'],
    queryFn: () => documentsApi.assetBlob(workspaceId, doc.id),
    staleTime: PPTX_ASSET_STALE_MS,
    gcTime: PPTX_ASSET_GC_MS,
  }).catch(() => undefined)
}

/** 悬停防抖：同一时刻只保留一个待执行任务，移出 / 卸载时取消 */
export function createPptxPrefetcher(
  prefetch: (doc: DocumentItem) => void,
  delay = PPTX_PREFETCH_DELAY_MS,
) {
  let timer: ReturnType<typeof setTimeout> | null = null

  const cancel = () => {
    if (timer === null) return
    clearTimeout(timer)
    timer = null
  }

  return {
    schedule(doc: DocumentItem) {
      cancel()
      timer = setTimeout(() => {
        timer = null
        prefetch(doc)
      }, delay)
    },
    cancel,
  }
}

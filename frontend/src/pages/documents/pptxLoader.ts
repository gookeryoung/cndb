/** PPTX 预览共享口径：渲染库模块级加载、原件 MIME 判定与原件缓存时长.
 *
 * 阅读器（PptxPreview）与全屏放映（PptxSlideshow）共用同一次动态 import，
 * StrictMode 双执行、重复打开都不再重复下载解析渲染库。
 */

import type { DocumentItem } from '@/api/documents'

export const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

/** 原件 blob 在前端内存缓存中的新鲜期 / 保留期（需求 0128 C4） */
export const PPTX_ASSET_STALE_MS = 10 * 60_000
export const PPTX_ASSET_GC_MS = 30 * 60_000

let pptxModulePromise: Promise<typeof import('pptx-preview')> | null = null

/** 模块级缓存：同一会话只解析一次渲染库 */
export const loadPptxModule = () => (pptxModulePromise ??= import('pptx-preview'))

/** 仅标准 OOXML .pptx 可纯前端渲染；旧版二进制 .ppt 仍下载查看 */
export function isPreviewablePptx(doc: Pick<DocumentItem, 'content_type' | 'asset_mime'>) {
  return doc.content_type === 'pptx' && (doc.asset_mime === PPTX_MIME || !doc.asset_mime)
}

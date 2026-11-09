/** PPTX 服务端 PDF 衍生预览：读取状态机与轮询（ADR 0129 P1）.
 *
 * 只暴露一个读取入口：``GET /asset/pdf`` 的 200 / 202 / 409 / 413 / 422 / 503
 * 统一归一为五种前端状态。除 ``ready`` 外都不算错误 —— 阅读器保留 0128 的
 * 客户端逐页预览，不因 PDF 链路不可用而阻断阅读。
 *
 * 轮询退避 2s → 3s → 5s，累计不超过 60s；页面隐藏时暂停，卸载（AbortSignal）
 * 立即停止，避免后台标签页持续打接口。
 */

import { documentsApi } from '@/api/documents'

/** 前端状态：pending 表示转换排队 / 进行中，ready 才可切换 PDF */
export type PptxPdfState = 'pending' | 'ready' | 'disabled' | 'unsupported' | 'too_large' | 'failed' | 'busy'

export interface PptxPdfResult {
  state: PptxPdfState
  /** 仅 ready 时存在 */
  blob?: Blob
}

/** 轮询退避（毫秒）：2s → 3s → 5s 后固定 5s（ADR 0129 §6） */
export const PPTX_PDF_RETRY_DELAYS_MS = [2000, 3000, 5000] as const
/** 单次打开最多等待 PDF 的时长；超过后保留客户端预览，不报错 */
export const PPTX_PDF_MAX_WAIT_MS = 60_000

export interface FetchPptxPdfOptions {
  signal?: AbortSignal
  /** 测试注入更短的退避；缺省用生产序列 */
  delays?: readonly number[]
  maxWaitMs?: number
  /**
   * 每次拿到状态就回调（含 202 轮询中间态）.
   *
   * 一次查询的 promise 只在链路结束（ready / 不可用 / 超时）时 resolve，
   * 调用方要靠这个回调才能显示「正在生成高清预览」。
   */
  onState?: (state: PptxPdfState) => void
}

/** HTTP 状态 → 前端状态；409 同时覆盖「未启用」与「非 PPTX」两种后端码 */
export function stateFromStatus(status: number): PptxPdfState {
  switch (status) {
    case 200:
      return 'ready'
    case 202:
      return 'pending'
    case 409:
      return 'disabled'
    case 413:
      return 'too_large'
    case 422:
      return 'failed'
    case 503:
      return 'busy'
    default:
      return 'failed'
  }
}

function abortError() {
  return new DOMException('aborted', 'AbortError')
}

/** 可取消的 sleep；abort 时立刻拒绝，不再发下一次请求 */
function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      reject(abortError())
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/** 页面隐藏时暂停轮询，回到可见后继续；abort 时拒绝以结束整条链路 */
function waitUntilVisible(signal?: AbortSignal) {
  if (typeof document === 'undefined' || !document.hidden) return Promise.resolve()
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      document.removeEventListener('visibilitychange', onChange)
      signal?.removeEventListener('abort', onAbort)
    }
    const onChange = () => {
      if (document.hidden) return
      cleanup()
      resolve()
    }
    const onAbort = () => {
      cleanup()
      reject(abortError())
    }
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    document.addEventListener('visibilitychange', onChange)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * 读取服务端 PDF：202 时按退避轮询，直到 ready / 不可用 / 超时。
 *
 * 不会抛出业务错误：任何失败都归一为状态值，调用方只做展示降级。
 * 仅在组件卸载导致 AbortSignal 触发时抛出 AbortError（react-query 会忽略）。
 */
export async function fetchPptxPdf(
  workspaceId: number,
  docId: number,
  { signal, delays = PPTX_PDF_RETRY_DELAYS_MS, maxWaitMs = PPTX_PDF_MAX_WAIT_MS, onState }: FetchPptxPdfOptions = {},
): Promise<PptxPdfResult> {
  let waited = 0
  let index = 0

  for (;;) {
    await waitUntilVisible(signal)
    const response = await documentsApi.assetPdf(workspaceId, docId, signal)
    const state = stateFromStatus(response.status)
    onState?.(state)
    if (state === 'ready') {
      // 200 但拿不到字节按失败降级，避免上层切到空 iframe
      if (!response.data) {
        onState?.('failed')
        return { state: 'failed' }
      }
      return { state, blob: response.data }
    }
    if (state !== 'pending') return { state }

    const delay = delays[Math.min(index, delays.length - 1)] ?? 5000
    index += 1
    waited += delay
    // 超过预算：保持 pending（客户端预览仍可用），不再继续请求
    if (waited > maxWaitMs) return { state: 'pending' }
    await sleep(delay, signal)
  }
}

/** 手动请求 / 重试一次转换（POST 不返回字节，只返回状态） */
export async function requestPptxPdf(workspaceId: number, docId: number): Promise<PptxPdfState> {
  const response = await documentsApi.requestAssetPdf(workspaceId, docId)
  return stateFromStatus(response.status)
}

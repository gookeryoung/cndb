/** AI 动作调用状态 hook —— 统一 idle / loading / success / error（ADR 0020 C11）.
 *
 * 定位：页面只声明「怎么发请求」，loading / 错误文案 / 结果缓存 / 取消语义由本 hook 统一处理，
 * 避免文档、导入、表格、分析各自复制一套状态机（ADR 0020 D16）。
 *
 * 约定：
 * - `run()` 永不抛错：成功返回结果，失败返回 null 并把可读文案放进 `error`
 *   （后端 FastAPI `detail` 优先，其次 axios 归一化后的 message，最后用调用方兜底文案）；
 * - `reset()` 关闭 / 取消后回到 idle，并让仍在飞行中的请求结果被丢弃（不会回写旧状态）；
 * - 请求函数每次渲染可以变（页面闭包依赖 workspaceId / docId），内部用 ref 取最新值。
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/** 一次 AI 动作的状态 */
export type LlmActionStatus = 'idle' | 'loading' | 'success' | 'error'

/** hook 状态（额外给出 `loading` 布尔值，调用点判断更直观） */
export interface LlmActionState<T> {
  status: LlmActionStatus
  loading: boolean
  /** 成功时的结果；出错 / 未开始时为 null */
  data: T | null
  /** 失败时的可读文案（后端 detail 优先）；成功 / 未开始时为 null */
  error: string | null
}

export interface UseLlmActionOptions {
  /** 请求失败且拿不到后端 detail 时的兜底文案（默认「AI 调用失败，请稍后重试」） */
  fallbackError?: string
}

export interface UseLlmActionResult<T, P> extends LlmActionState<T> {
  /** 发起一次调用；成功 resolve 结果，失败 resolve null（错误已写进 state.error） */
  run: (payload: P) => Promise<T | null>
  /** 回到 idle 并丢弃在途请求的结果 */
  reset: () => void
}

const DEFAULT_ERROR = 'AI 调用失败，请稍后重试'

/** 把 FastAPI detail（字符串 / 校验错误数组 / 对象）归一化为可读文案 */
function detailText(detail: unknown): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail)) {
    const parts = detail
      .map(item => {
        if (item == null) return ''
        if (typeof item === 'string') return item
        if (typeof item === 'object') {
          const msg = (item as { msg?: unknown }).msg
          return msg != null ? String(msg) : JSON.stringify(item)
        }
        return String(item)
      })
      .filter(part => part.trim().length > 0)
    return parts.length > 0 ? parts.join('；') : null
  }
  if (typeof detail === 'object') {
    const msg = (detail as { msg?: unknown }).msg
    return msg != null ? String(msg) : JSON.stringify(detail)
  }
  return String(detail)
}

/** AI 错误文案归一化：后端 detail > 超时提示 > 网络 / 未知兜底文案. */
export function normalizeLlmError(err: unknown, fallbackError: string = DEFAULT_ERROR): string {
  const errLike = err as
    | { response?: { data?: unknown }; message?: string; code?: string }
    | null
    | undefined
  const detail = detailText(
    (errLike?.response?.data as { detail?: unknown } | undefined)?.detail,
  )
  if (detail) return detail
  const rawMessage = typeof errLike?.message === 'string' ? errLike.message.trim() : ''
  // axios 的超时是 ECONNABORTED（无 response），后端限流 / 上游失败会带 detail
  if (errLike?.code === 'ECONNABORTED' || /timeout/i.test(rawMessage)) {
    return 'AI 调用超时（30 秒），请稍后重试或缩小选区'
  }
  return rawMessage || fallbackError
}

/**
 * 通用 AI 动作 hook。
 *
 * @param request 发起请求的函数（入参即 `run(payload)` 的 payload）
 * @param options 兜底错误文案等
 *
 * 用法：
 * ```ts
 * const polish = useLlmAction((payload: DocumentAiPolishPayload) =>
 *   documentsApi.aiAction(wid, id, 'polish', payload))
 * void polish.run({ selection, instruction: 'polish' })
 * ```
 */
export function useLlmAction<T, P = Record<string, never>>(
  request: (payload: P) => Promise<T>,
  options: UseLlmActionOptions = {},
): UseLlmActionResult<T, P> {
  const [state, setState] = useState<LlmActionState<T>>({
    status: 'idle',
    loading: false,
    data: null,
    error: null,
  })

  const requestRef = useRef(request)
  useEffect(() => {
    requestRef.current = request
  })

  /** 请求序号：reset / 卸载 / 新一次 run 都会让旧请求的结果失效 */
  const seqRef = useRef(0)
  useEffect(() => () => {
    seqRef.current += 1
  }, [])

  const { fallbackError } = options

  const reset = useCallback(() => {
    seqRef.current += 1
    setState({ status: 'idle', loading: false, data: null, error: null })
  }, [])

  const run = useCallback(
    async (payload: P): Promise<T | null> => {
      const seq = ++seqRef.current
      setState(prev => ({ status: 'loading', loading: true, data: prev.data, error: null }))
      try {
        const data = await requestRef.current(payload)
        if (seq !== seqRef.current) return null
        setState({ status: 'success', loading: false, data, error: null })
        return data
      } catch (err) {
        if (seq !== seqRef.current) return null
        setState({ status: 'error', loading: false, data: null, error: normalizeLlmError(err, fallbackError) })
        return null
      }
    },
    [fallbackError],
  )

  return { ...state, run, reset }
}

export default useLlmAction

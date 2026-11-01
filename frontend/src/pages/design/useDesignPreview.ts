/** 设计预览循环 —— 防抖调 preview 端点，带参数覆盖（ADR 0079 D4）.
 *
 * 竞态口径：请求带递增序号，**最后胜出**——过期响应（防抖窗口内内容又变了）
 * 一律丢弃，不做「先回先画」；编译与求值全部在后端完成（I1，前端零求值）。
 */

import { useEffect, useRef, useState } from 'react'
import { designsApi } from '@/api'
import type { DesignDiagnostic, DesignIR } from '@/api'

export interface DesignPreviewState {
  /** 防抖窗口内（已排队未发出 / 已发出未回包） */
  compiling: boolean
  /** 最近一次编译结论（无结果时按 true 空态处理） */
  ok: boolean
  ir: DesignIR | null
  diagnostics: DesignDiagnostic[]
}

export interface UseDesignPreviewOptions {
  /** 防抖毫秒（默认 300） */
  delay?: number
  /** 关闭时跳过请求（如详情未加载完成） */
  enabled?: boolean
}

const EMPTY_STATE: DesignPreviewState = { compiling: false, ok: true, ir: null, diagnostics: [] }

/** 防抖预览：内容或参数覆盖变化后延迟请求，过期响应按序号丢弃 */
export function useDesignPreview(
  wid: string,
  content: string,
  overrides: Record<string, number>,
  options?: UseDesignPreviewOptions,
): DesignPreviewState {
  const { delay = 300, enabled = true } = options ?? {}
  const [state, setState] = useState<DesignPreviewState>(EMPTY_STATE)
  const seqRef = useRef(0)
  // overrides 是每次渲染新建的对象（受控面板），序列化为 key 参与依赖比较
  const overridesKey = JSON.stringify(overrides)

  useEffect(() => {
    if (!wid || !enabled) {
      setState(EMPTY_STATE)
      return
    }
    seqRef.current += 1
    const seq = seqRef.current
    const ov = JSON.parse(overridesKey || '{}') as Record<string, number>
    setState(prev => ({ ...prev, compiling: true }))
    const timer = setTimeout(() => {
      designsApi
        .preview(wid, { content, overrides: Object.keys(ov).length > 0 ? ov : null })
        .then(result => {
          if (seq !== seqRef.current) return
          setState({ compiling: false, ok: result.ok, ir: result.ir, diagnostics: result.diagnostics })
        })
        .catch(() => {
          if (seq !== seqRef.current) return
          // 网络错误等：清空渲染结果，诊断区提示由页面兜底文案承担
          setState({ compiling: false, ok: false, ir: null, diagnostics: [] })
        })
    }, delay)
    return () => clearTimeout(timer)
  }, [wid, content, overridesKey, delay, enabled])

  return state
}

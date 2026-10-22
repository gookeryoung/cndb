/** useLlmAction 单元测试 —— 统一状态机 / 后端 detail 优先 / reset 丢弃在途结果（ADR 0020 C11）.
 *
 * 请求本身走真实 api 封装，网络经 MSW mock：不触达真实模型。
 */

import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { documentsApi } from '@/api/documents'
import type { DocumentAiPolishPayload } from '@/api/documents'
import { server } from '@/test/msw'
import { normalizeLlmError, useLlmAction } from './useLlmAction'

type PolishPayload = DocumentAiPolishPayload

function mockPolishOnce(
  result: { text: string },
  options: { status?: number; detail?: string; delayMs?: number } = {},
) {
  const bodies: Record<string, unknown>[] = []
  server.use(
    http.post('/api/v1/workspaces/:wid/documents/:docId/ai/actions/polish', async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>)
      if (options.delayMs) await new Promise(resolve => setTimeout(resolve, options.delayMs))
      if (options.status && options.status >= 400) {
        return HttpResponse.json({ detail: options.detail ?? 'AI 调用失败' }, { status: options.status })
      }
      return HttpResponse.json({
        action: 'document.polish',
        run_id: 8891,
        model: 'deepseek-chat',
        usage: { prompt_tokens: 12, completion_tokens: 8, total_tokens: 20 },
        result,
      })
    }),
  )
  return bodies
}

function usePolishAction() {
  return useLlmAction((payload: PolishPayload) => documentsApi.aiAction(10, 2, 'polish', payload))
}

describe('normalizeLlmError', () => {
  it('优先后端 detail 字符串', () => {
    expect(
      normalizeLlmError({ response: { data: { detail: '选区超长（最多 4000 字）' }, status: 400 } }),
    ).toBe('选区超长（最多 4000 字）')
  })

  it('兼容 FastAPI 校验错误数组', () => {
    expect(
      normalizeLlmError({
        response: { data: { detail: [{ loc: ['body', 'selection'], msg: '字段不能为空' }, { msg: '指令非法' }] } },
      }),
    ).toBe('字段不能为空；指令非法')
  })

  it('无 detail 时用归一化后的 message', () => {
    expect(normalizeLlmError({ message: 'Network Error' })).toBe('Network Error')
  })

  it('超时给出中文提示', () => {
    expect(normalizeLlmError({ code: 'ECONNABORTED', message: 'timeout of 30000ms exceeded' })).toContain(
      '超时（30 秒）',
    )
  })

  it('完全无法识别时用兜底文案', () => {
    expect(normalizeLlmError(undefined)).toBe('AI 调用失败，请稍后重试')
    expect(normalizeLlmError({}, '润色失败')).toBe('润色失败')
  })
})

describe('useLlmAction', () => {
  it('初始为 idle', () => {
    const { result } = renderHook(() => usePolishAction())
    expect(result.current.status).toBe('idle')
    expect(result.current.loading).toBe(false)
    expect(result.current.data).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('成功：loading → success，返回动作响应并缓存结果', async () => {
    const bodies = mockPolishOnce({ text: '该方案需重新梳理流程。' })
    const { result } = renderHook(() => usePolishAction())

    await act(async () => {
      await result.current.run({ selection: '该方案需要重新梳理流程。', instruction: 'polish' })
    })

    expect(bodies).toEqual([{ selection: '该方案需要重新梳理流程。', instruction: 'polish' }])
    expect(result.current.status).toBe('success')
    expect(result.current.error).toBeNull()
    expect(result.current.data?.model).toBe('deepseek-chat')
    expect(result.current.data?.usage.total_tokens).toBe(20)
    expect(result.current.data?.result.text).toBe('该方案需重新梳理流程。')
  })

  it('失败：error 取后端 detail，run 返回 null 且不抛错', async () => {
    mockPolishOnce({ text: '' }, { status: 400, detail: '请先选中文本后再调用' })
    const { result } = renderHook(() => usePolishAction())

    let returned: unknown = 'not-called'
    await act(async () => {
      returned = await result.current.run({ selection: 'x', instruction: 'polish' })
    })

    expect(returned).toBeNull()
    expect(result.current.status).toBe('error')
    expect(result.current.error).toBe('请先选中文本后再调用')
    expect(result.current.data).toBeNull()
  })

  it('reset：回到 idle 并清空结果 / 错误', async () => {
    mockPolishOnce({ text: '新文本' })
    const { result } = renderHook(() => usePolishAction())

    await act(async () => {
      await result.current.run({ selection: '原文', instruction: 'polish' })
    })
    expect(result.current.status).toBe('success')

    act(() => {
      result.current.reset()
    })
    expect(result.current.status).toBe('idle')
    expect(result.current.data).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('reset 后丢弃在途请求结果（不会把旧结果写回）', async () => {
    mockPolishOnce({ text: '迟到的结果' }, { delayMs: 60 })
    const { result } = renderHook(() => usePolishAction())

    let pending: Promise<unknown> = Promise.resolve()
    act(() => {
      pending = result.current.run({ selection: '原文', instruction: 'polish' })
    })
    act(() => {
      result.current.reset()
    })
    await act(async () => {
      await pending
    })

    expect(result.current.status).toBe('idle')
    expect(result.current.data).toBeNull()
  })
})

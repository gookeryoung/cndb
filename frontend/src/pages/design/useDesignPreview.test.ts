/** useDesignPreview 测试 —— 防抖 / 竞态（最后胜出）/ overrides 传参 / 网络错误清空（ADR 0079 §7）.
 *
 * 用真实定时器 + msw delay 模拟网络时序，避免 fake timers 与 msw 交互的复杂性.
 */

import { describe, expect, it } from 'vitest'
import { delay as mswDelay, http, HttpResponse } from 'msw'
import { act, waitFor } from '@testing-library/react'
import { renderHookProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { DesignIR, DesignPreviewResult } from '@/api'
import { useDesignPreview } from './useDesignPreview'

const WID = '10'
const PREVIEW_PATH = '/api/v1/workspaces/10/designs/preview'

/** 记录每次 preview 请求体（content + overrides） */
const previewBodies: Array<{ content: string; overrides?: Record<string, number> | null }> = []

/** 单盒 IR：size[0] 作为标记位，竞态用例据此区分「谁胜出」 */
function irOf(mark: number): DesignIR {
  return {
    version: 2,
    units: { length: 'mm', angle: 'deg' },
    params: [],
    nodes: [{ op: 'box', size: [mark, 1, 1] }],
  }
}

function boxMark(ir: DesignIR | null): number | undefined {
  const node = ir?.nodes[0]
  return node && 'size' in node ? node.size[0] : undefined
}

/** 默认 preview handler：内容含「慢请求」时延迟 150ms 回包，快请求即时回包 */
function usePreviewHandler() {
  previewBodies.length = 0
  server.use(http.post(PREVIEW_PATH, async ({ request }) => {
    const body = await request.json() as { content: string; overrides?: Record<string, number> | null }
    previewBodies.push(body)
    if (body.content.includes('慢请求')) await mswDelay(150)
    const mark = body.content.includes('快') ? 9 : 1
    const result: DesignPreviewResult = { ok: true, ir: irOf(mark), diagnostics: [] }
    return HttpResponse.json(result)
  }))
}

describe('useDesignPreview', () => {
  it('enabled=false 时不发请求且状态为空态', async () => {
    usePreviewHandler()
    const { result } = renderHookProviders(() =>
      useDesignPreview(WID, 'box()', {}, { enabled: false }))

    await act(async () => { await new Promise(resolve => setTimeout(resolve, 60)) })
    expect(previewBodies).toHaveLength(0)
    expect(result.current).toEqual({ compiling: false, ok: true, ir: null, diagnostics: [] })
  })

  it('防抖窗口内连续变更只发最后一次请求', async () => {
    usePreviewHandler()
    let content = '第一版'
    const rendered = renderHookProviders(() =>
      useDesignPreview(WID, content, {}, { delay: 30 }))

    // 防抖窗口内（30ms）再次变更：前一次已排队未发出，应被清理
    content = '第二版'
    rendered.rerender()

    await waitFor(() => expect(previewBodies).toHaveLength(1))
    expect(previewBodies[0]!.content).toBe('第二版')
    await waitFor(() => expect(rendered.result.current.compiling).toBe(false))
  })

  it('竞态：慢请求过期回包被丢弃，快请求结果胜出', async () => {
    usePreviewHandler()
    let content = '慢请求'
    const rendered = renderHookProviders(() =>
      useDesignPreview(WID, content, {}, { delay: 30 }))

    // 慢请求已发出（在途）
    await waitFor(() => expect(previewBodies).toHaveLength(1))

    // 慢请求在途时改为快内容：新序号请求即时回包
    content = '快内容'
    rendered.rerender()
    await waitFor(() => expect(previewBodies).toHaveLength(2))
    await waitFor(() => expect(boxMark(rendered.result.current.ir)).toBe(9))

    // 等慢请求过期回包（150ms 延迟）：序号已过期，不得覆盖胜出结果
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 220)) })
    expect(boxMark(rendered.result.current.ir)).toBe(9)
    expect(rendered.result.current.compiling).toBe(false)
  })

  it('overrides 变化触发重编译并进入请求体', async () => {
    usePreviewHandler()
    let overrides: Record<string, number> = {}
    const rendered = renderHookProviders(() =>
      useDesignPreview(WID, 'box()', overrides, { delay: 30 }))

    await waitFor(() => expect(previewBodies).toHaveLength(1))
    expect(previewBodies[0]!.overrides).toBeNull()

    overrides = { width: 100 }
    rendered.rerender()
    await waitFor(() => expect(previewBodies).toHaveLength(2))
    expect(previewBodies[1]!.overrides).toEqual({ width: 100 })
    await waitFor(() => expect(rendered.result.current.compiling).toBe(false))
  })

  it('网络错误时清空渲染结果且 compiling 复位', async () => {
    server.use(http.post(PREVIEW_PATH, () =>
      HttpResponse.json({ detail: '服务器内部错误' }, { status: 500 })))

    const rendered = renderHookProviders(() =>
      useDesignPreview(WID, 'box()', {}, { delay: 30 }))

    await waitFor(() => expect(rendered.result.current.ok).toBe(false))
    expect(rendered.result.current.ir).toBeNull()
    expect(rendered.result.current.diagnostics).toEqual([])
    expect(rendered.result.current.compiling).toBe(false)
  })
})

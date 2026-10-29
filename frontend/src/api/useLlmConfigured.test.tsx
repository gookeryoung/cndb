/** useLlmConfigured 单测 —— 需求 0069：AI 入口显隐的可用性判定.
 *
 * - configured=true（默认 MSW handler）→ true；
 * - configured=false（MSW 覆盖）→ false；
 * - 接口失败（404）→ 安全降级为 false。
 */

import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'

import { server } from '@/test/msw'
import { useLlmConfigured } from './useLlmConfigured'

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useLlmConfigured', () => {
  it('已配置（configured=true）返回 true', async () => {
    const { result } = renderHook(() => useLlmConfigured(), { wrapper })
    await waitFor(() => expect(result.current).toBe(true))
  })

  it('未配置（configured=false）返回 false', async () => {
    server.use(
      http.get('/api/v1/llm/config', () => HttpResponse.json({
        configured: false, base_url: '', model: '', has_api_key: false,
        system_prompt: '', default_system_prompt: '',
      })),
    )
    const { result } = renderHook(() => useLlmConfigured(), { wrapper })
    await waitFor(() => expect(result.current).toBe(false))
  })

  it('接口失败安全降级为 false（AI 入口隐藏属安全侧）', async () => {
    server.use(http.get('/api/v1/llm/config', () => new HttpResponse(null, { status: 500 })))
    const { result } = renderHook(() => useLlmConfigured(), { wrapper })
    await waitFor(() => expect(result.current).toBe(false))
  })
})

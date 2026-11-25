/** useCapabilities 单元测试 —— 能力位单一来源 / fail-closed / 来源归因（ADR 0153 P0）.
 *
 * 网络经 MSW mock，不触达真实后端；默认 handler 按 owner 全量能力返回，
 * 单用例用 server.use 覆盖为 viewer / 404。
 */

import { describe, expect, it } from 'vitest'
import { waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { server } from '@/test/msw'
import { renderHookProviders } from '@/test/render-providers'
import { useCapabilities } from './useCapabilities'

function mockCapabilities(payload: {
  data_role: string | null
  team_role?: string | null
  capabilities: string[]
  sources?: Record<string, string>
}) {
  server.use(
    http.get('/api/v1/workspaces/:wid/capabilities', () =>
      HttpResponse.json({ team_role: null, sources: {}, ...payload })),
  )
}

describe('useCapabilities 能力位 Hook', () => {
  it('owner 拥有全部能力位，且按能力位判定', async () => {
    const { result } = renderHookProviders(() => useCapabilities('10'))

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.dataRole).toBe('owner')
    expect(result.current.can('EDIT_SETTINGS')).toBe(true)
    expect(result.current.can('MANAGE_MEMBERS')).toBe(true)
    expect(result.current.can('RESTORE')).toBe(true)
    expect(result.current.sources.manage).toBe('workspace_member:owner')
  })

  it('viewer 只能 READ，管理能力位一律 false', async () => {
    mockCapabilities({
      data_role: 'viewer',
      capabilities: ['READ'],
      sources: { data: 'workspace_member:viewer' },
    })
    const { result } = renderHookProviders(() => useCapabilities('10'))

    await waitFor(() => expect(result.current.dataRole).toBe('viewer'))
    expect(result.current.can('READ')).toBe(true)
    expect(result.current.can('WRITE')).toBe(false)
    expect(result.current.can('EXPORT')).toBe(false)
    expect(result.current.can('EDIT_SETTINGS')).toBe(false)
  })

  it('加载期 fail-closed：未拿到载荷时任何能力位都为 false', () => {
    mockCapabilities({ data_role: 'owner', capabilities: ['READ', 'EDIT_SETTINGS'] })
    const { result } = renderHookProviders(() => useCapabilities('10'))

    expect(result.current.capabilities).toBeNull()
    expect(result.current.can('READ')).toBe(false)
    expect(result.current.can('EDIT_SETTINGS')).toBe(false)
  })

  it('非成员（404）时不抛错、能力位全 false', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/capabilities', () =>
        HttpResponse.json({ detail: '工作区不存在' }, { status: 404 })),
    )
    const { result } = renderHookProviders(() => useCapabilities('10'))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.capabilities).toBeNull()
    expect(result.current.dataRole).toBeNull()
    expect(result.current.can('READ')).toBe(false)
  })

  it('wid 为空时不发请求，能力位全 false', () => {
    const { result } = renderHookProviders(() => useCapabilities(null))

    expect(result.current.isLoading).toBe(false)
    expect(result.current.capabilities).toBeNull()
    expect(result.current.can('READ')).toBe(false)
  })
})

/**
 * useRealtime 桥接测试 —— 真实消息 → store / React Query 缓存失效.
 *
 * 用 mock 的 RealtimeClient 捕获 handlers，直接喂服务端消息，验证：
 * presence.* 更新在线成员、doc.lock 记录编辑者、event.created 按 action 失效对应缓存、
 * 未知消息不炸、卸载时断开并清空成员。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { waitFor } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'

type Handlers = {
  onMessage?: (m: { type: string; ts: string; payload: Record<string, unknown> }) => void
  onStatus?: (s: string) => void
}

const captured: { handlers: Handlers | null; closed: number; presence: Array<[number | null, string | null]> } = {
  handlers: null,
  closed: 0,
  presence: [],
}

vi.mock('./realtimeClient', async () => {
  const actual = await vi.importActual<typeof import('./realtimeClient')>('./realtimeClient')
  class MockRealtimeClient {
    connect(_wid: unknown, handlers: Handlers) {
      captured.handlers = handlers
    }
    close() {
      captured.closed += 1
    }
    updatePresence(documentId: number | null, mode: string | null) {
      captured.presence.push([documentId, mode])
    }
    send() {
      return true
    }
    getStatus() {
      return 'open'
    }
  }
  return { ...actual, default: MockRealtimeClient, RealtimeClient: MockRealtimeClient }
})

const { useRealtime, useDocumentViewers, useDocumentEditing } = await import('./useRealtime')
const { useRealtimeStore } = await import('./realtimeStore')

function Probe({ documentId = 5 }: { documentId?: number }) {
  const { status, members, updatePresence } = useRealtime('9')
  const viewers = useDocumentViewers(documentId)
  const editing = useDocumentEditing(documentId)
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="members">{members.length}</span>
      <span data-testid="viewers">{viewers.length}</span>
      <span data-testid="editing">{editing?.username ?? '-'}</span>
      <button data-testid="claim" onClick={() => updatePresence(documentId, 'editing')}>
        claim
      </button>
    </div>
  )
}

beforeEach(() => {
  captured.handlers = null
  captured.closed = 0
  captured.presence = []
  useRealtimeStore.getState().reset()
})

describe('useRealtime 桥接', () => {
  it('presence.sync 更新在线成员与连接状态', async () => {
    renderProviders(<Probe />)
    await waitFor(() => expect(captured.handlers).not.toBeNull())

    captured.handlers!.onStatus?.('open')
    captured.handlers!.onMessage?.({
      type: 'presence.sync',
      ts: 't',
      payload: {
        members: [
          { user_id: 1, username: 'alice', connections: 1, document_id: 5, mode: 'editing' },
          { user_id: 2, username: 'bob', connections: 1, document_id: 5, mode: 'viewing' },
        ],
      },
    })

    await waitFor(() => {
      expect(useRealtimeStore.getState().members).toHaveLength(2)
      expect(useRealtimeStore.getState().status).toBe('open')
    })
  })

  it('doc.lock 记录编辑者，释放后清空', async () => {
    renderProviders(<Probe />)
    await waitFor(() => expect(captured.handlers).not.toBeNull())

    captured.handlers!.onMessage?.({
      type: 'doc.lock',
      ts: 't',
      payload: { document_id: 5, locked: true, user_id: 3, username: 'carol' },
    })
    await waitFor(() => {
      expect(useRealtimeStore.getState().editingDocument[5]?.username).toBe('carol')
    })

    captured.handlers!.onMessage?.({
      type: 'doc.lock',
      ts: 't',
      payload: { document_id: 5, locked: false, user_id: 3, username: 'carol' },
    })
    await waitFor(() => {
      expect(useRealtimeStore.getState().editingDocument[5]).toBeUndefined()
    })
  })

  it('event.created 按 action 失效对应 React Query 缓存', async () => {
    const { queryClient } = renderProviders(<Probe />)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await waitFor(() => expect(captured.handlers).not.toBeNull())

    captured.handlers!.onMessage?.({
      type: 'event.created',
      ts: 't',
      payload: { action: 'record.create', workspace_id: 9 },
    })
    captured.handlers!.onMessage?.({
      type: 'event.created',
      ts: 't',
      payload: { action: 'auth.login', workspace_id: null },
    })
    captured.handlers!.onMessage?.({ type: 'nonsense', ts: 't', payload: {} })

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalled()
    })
    const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey))
    expect(keys).toContain(JSON.stringify(['table-records']))
    // 认证类事件不触发刷新
    expect(keys.every((k) => !k.includes('auth'))).toBe(true)
  })

  it('卸载时断开连接并清空成员', async () => {
    const { unmount } = renderProviders(<Probe />)
    await waitFor(() => expect(captured.handlers).not.toBeNull())

    captured.handlers!.onMessage?.({
      type: 'presence.sync',
      ts: 't',
      payload: { members: [{ user_id: 1, username: 'alice', connections: 1, document_id: null, mode: null }] },
    })
    await waitFor(() => expect(useRealtimeStore.getState().members).toHaveLength(1))

    unmount()
    await waitFor(() => {
      expect(captured.closed).toBe(1)
      expect(useRealtimeStore.getState().members).toHaveLength(0)
    })
  })

  it('updatePresence 透传给客户端', async () => {
    const { getByTestId } = renderProviders(<Probe />)
    await waitFor(() => expect(captured.handlers).not.toBeNull())

    getByTestId('claim').click()
    await waitFor(() => {
      expect(captured.presence).toContainEqual([5, 'editing'])
    })
  })
})

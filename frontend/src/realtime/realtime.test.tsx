/**
 * 实时层测试 —— 客户端（连接/心跳/重连/分发）、事件桥、在线成员组件.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import RealtimeClient, { buildWsUrl } from './realtimeClient'
import { isRefreshableAction, queryKeysForAction } from './eventBridge'
import { CollaborationStatusTag, DocumentViewers, realtimeStatusText } from './RealtimeIndicators'
import type { PresenceMember } from './realtimeClient'

// ── WebSocket 替身 ──────────────────────────────────────
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  static CLOSED = 3
  url: string
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  emit(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.()
  }

  send(data: string) {
    this.sent.push(data)
  }
}

beforeEach(() => {
  FakeWebSocket.instances = []
  // jsdom 的 WebSocket 属性只读，必须用 vi.stubGlobal 打桩
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('buildWsUrl', () => {
  it('带工作区与令牌，并按当前协议选择 ws/wss', () => {
    const url = buildWsUrl(7, 'tok-1')
    expect(url).toContain('/api/v1/ws?')
    expect(url).toContain('workspace_id=7')
    expect(url).toContain('token=tok-1')
    expect(url.startsWith('ws://')).toBe(true)
  })

  it('无令牌时不带 token 参数（单机模式）', () => {
    expect(buildWsUrl(3, null)).not.toContain('token=')
  })
})

describe('RealtimeClient', () => {
  it('连接后状态为 open，并把服务端 ping 回以 pong', () => {
    const statuses: string[] = []
    const messages: unknown[] = []
    const client = new RealtimeClient()
    client.connect(9, {
      onStatus: (s) => statuses.push(s),
      onMessage: (m) => messages.push(m),
    })

    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toContain('workspace_id=9')
    ws.open()
    ws.emit({ type: 'ping', ts: 't', payload: {} })
    ws.emit({ type: 'pong', ts: 't', payload: {} })
    ws.emit({ type: 'presence.sync', ts: 't', payload: { members: [] } })

    expect(statuses).toContain('open')
    expect(ws.sent.map((s) => JSON.parse(s).type)).toEqual(['pong'])
    // ping/pong 不派发给业务（只有业务消息进 onMessage）
    expect(messages).toHaveLength(1)
    expect((messages[0] as { type: string }).type).toBe('presence.sync')
    client.close()
  })

  it('updatePresence 发送 presence.update 消息', () => {
    const client = new RealtimeClient()
    client.connect(1, {})
    const ws = FakeWebSocket.instances[0]
    ws.open()
    client.updatePresence(42, 'editing')
    expect(JSON.parse(ws.sent[0])).toMatchObject({
      type: 'presence.update',
      payload: { document_id: 42, mode: 'editing' },
    })
    client.close()
  })

  it('断线后按退避重连（重连期间状态为 reconnecting）', () => {
    vi.useFakeTimers()
    const statuses: string[] = []
    const client = new RealtimeClient()
    client.connect(1, { onStatus: (s) => statuses.push(s) })
    FakeWebSocket.instances[0].open()
    FakeWebSocket.instances[0].close()

    expect(statuses).toContain('reconnecting')
    expect(FakeWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(2000) // 首次退避 ≈1s（含抖动）
    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2)
    client.close()
  })

  it('close 之后不再重连', () => {
    vi.useFakeTimers()
    const client = new RealtimeClient()
    client.connect(1, {})
    const ws = FakeWebSocket.instances[0]
    ws.open()
    client.close()
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(client.getStatus()).toBe('closed')
  })

  it('未连接时 send 返回 false（不抛异常）', () => {
    const client = new RealtimeClient()
    expect(client.send({ type: 'x' })).toBe(false)
    expect(client.getStatus()).toBe('idle')
  })
})

describe('事件桥 queryKeysForAction', () => {
  it('记录/文档/用户/工作区事件映射到对应缓存前缀', () => {
    expect(queryKeysForAction('record.create')).toContainEqual(['table-records'])
    expect(queryKeysForAction('document.update')).toContainEqual(['documents'])
    expect(queryKeysForAction('user.role_change')).toContainEqual(['admin-users'])
    expect(queryKeysForAction('workspace.member_added')).toContainEqual(['workspaces'])
  })

  it('认证类事件不触发刷新', () => {
    expect(queryKeysForAction('auth.login')).toEqual([])
    expect(isRefreshableAction('auth.login')).toBe(false)
    expect(isRefreshableAction('record.update')).toBe(true)
  })

  it('未知动作安全返回空数组', () => {
    expect(queryKeysForAction('nonsense.action')).toEqual([])
  })
})

describe('实时 UI 组件', () => {
  const member = (over: Partial<PresenceMember> = {}): PresenceMember => ({
    user_id: 1,
    username: 'alice',
    connections: 1,
    document_id: 5,
    mode: 'viewing',
    ...over,
  })

  it('协作状态标识按状态渲染文案', () => {
    render(<CollaborationStatusTag status="open" />)
    expect(screen.getByTestId('collab-status')).toHaveTextContent('协作在线')
    expect(realtimeStatusText('reconnecting')).toBe('协作重连中')
  })

  it('未接入时不渲染协作状态标识', () => {
    const { container } = render(<CollaborationStatusTag status="idle" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('在线成员展示用户名、编辑中标记与"我"的标识', () => {
    render(<DocumentViewers members={[member(), member({ user_id: 2, username: 'bob', mode: 'editing' })]} currentUserId={1} />)
    expect(screen.getByTestId('doc-viewer-1')).toHaveTextContent('alice（我）')
    expect(screen.getByTestId('doc-viewer-2')).toHaveTextContent('bob · 编辑中')
    expect(screen.getByText('共 2 人在线')).toBeInTheDocument()
  })

  it('无人在线时不渲染', () => {
    const { container } = render(<DocumentViewers members={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

/** 实时通道客户端 —— WebSocket 连接、心跳、自动重连、消息分发.
 *
 * 协议见后端 `core/realtime.py`：信封 `{type, ts, payload}`。
 * - 服务端每 25s 发 `ping`，客户端必须回 `pong`（否则连接会被心跳超时关闭）；
 * - 断线自动重连（指数退避 1s → 30s，带抖动）；
 * - 页面变为可见时立即尝试重连（移动端切回前台/锁屏恢复场景）。
 */

import { getToken } from '@/api/client'

export type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface RealtimeMessage {
  type: string
  ts: string
  payload: Record<string, unknown>
}

export interface PresenceMember {
  user_id: number
  username: string
  connections: number
  document_id: number | null
  mode: string | null
}

export interface RealtimeHandlers {
  onMessage?: (message: RealtimeMessage) => void
  onStatus?: (status: RealtimeStatus) => void
}

const BASE_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30_000
/** 超过该时长未收到任何消息则主动重连（服务端 25s 一个 ping，留足余量） */
const SILENCE_TIMEOUT_MS = 90_000

/** 构造 WS 地址（token 走查询参数：浏览器 WebSocket 无法自定义请求头） */
export function buildWsUrl(workspaceId: number | string, token: string | null = getToken()): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const params = new URLSearchParams({ workspace_id: String(workspaceId) })
  if (token) params.set('token', token)
  return `${scheme}://${window.location.host}/api/v1/ws?${params.toString()}`
}

export class RealtimeClient {
  private ws: WebSocket | null = null
  private workspaceId: number | string | null = null
  private handlers: RealtimeHandlers = {}
  private attempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private silenceTimer: ReturnType<typeof setTimeout> | null = null
  private manuallyClosed = false
  private status: RealtimeStatus = 'idle'

  /** 建立连接（重复调用会先断开旧连接） */
  connect(workspaceId: number | string, handlers: RealtimeHandlers = {}): void {
    this.close()
    this.manuallyClosed = false
    this.workspaceId = workspaceId
    this.handlers = handlers
    this.open()
  }

  /** 主动断开并停止重连 */
  close(): void {
    this.manuallyClosed = true
    this.clearTimers()
    if (this.ws) {
      try {
        this.ws.onclose = null
        this.ws.onerror = null
        this.ws.onmessage = null
        this.ws.close()
      } catch {
        /* 忽略：已关闭 */
      }
      this.ws = null
    }
    this.attempt = 0
    this.setStatus('closed')
  }

  /** 上报"我正在查看/编辑哪份文档" */
  updatePresence(documentId: number | null, mode: 'viewing' | 'editing' | null): void {
    this.send({ type: 'presence.update', payload: { document_id: documentId, mode } })
  }

  send(message: Record<string, unknown>): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
    try {
      this.ws.send(JSON.stringify(message))
      return true
    } catch {
      return false
    }
  }

  getStatus(): RealtimeStatus {
    return this.status
  }

  /** 页面重新可见时立即重连（不等退避） */
  retryNow(): void {
    if (this.manuallyClosed || this.workspaceId === null) return
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return
    this.clearTimers()
    this.attempt = 0
    this.open()
  }

  private open(): void {
    if (this.workspaceId === null) return
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting')
    let socket: WebSocket
    try {
      socket = new WebSocket(buildWsUrl(this.workspaceId))
    } catch {
      this.scheduleReconnect()
      return
    }
    this.ws = socket

    socket.onopen = () => {
      this.attempt = 0
      this.setStatus('open')
      this.resetSilenceTimer()
    }

    socket.onmessage = (event: MessageEvent) => {
      this.resetSilenceTimer()
      let message: RealtimeMessage | null = null
      try {
        message = JSON.parse(String(event.data)) as RealtimeMessage
      } catch {
        return
      }
      if (!message || typeof message.type !== 'string') return
      // 心跳：必须回应 pong，否则服务端会按静默超时断开
      if (message.type === 'ping') {
        this.send({ type: 'pong' })
        return
      }
      if (message.type === 'pong') return
      this.handlers.onMessage?.(message)
    }

    socket.onerror = () => {
      // 详细错误由 onclose 统一处理（浏览器不提供错误详情）
    }

    socket.onclose = () => {
      this.ws = null
      if (this.manuallyClosed) return
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.manuallyClosed) return
    this.clearTimers()
    this.attempt += 1
    const backoff = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** (this.attempt - 1))
    // 抖动：避免多客户端同时重连打爆服务端
    const delay = Math.round(backoff * (0.7 + Math.random() * 0.6))
    this.setStatus('reconnecting')
    this.reconnectTimer = setTimeout(() => this.open(), delay)
  }

  private resetSilenceTimer(): void {
    if (this.silenceTimer) clearTimeout(this.silenceTimer)
    this.silenceTimer = setTimeout(() => {
      // 长时间无任何消息：连接可能已半开，主动重连
      if (this.ws) {
        try {
          this.ws.close()
        } catch {
          /* 忽略 */
        }
      }
    }, SILENCE_TIMEOUT_MS)
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    if (this.silenceTimer) clearTimeout(this.silenceTimer)
    this.reconnectTimer = null
    this.silenceTimer = null
  }

  private setStatus(status: RealtimeStatus): void {
    if (this.status === status) return
    this.status = status
    this.handlers.onStatus?.(status)
  }
}

export default RealtimeClient

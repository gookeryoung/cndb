/** 实时协作 Hook —— 连接工作区通道，驱动在线状态与缓存失效.
 *
 * 用法（MainLayout）：`const { status, updatePresence } = useRealtime(wid)`
 * 页面级在线状态：`useDocumentViewers(documentId)`
 *
 * 行为：
 * - `wid` 变化（切工作区）时重连；
 * - 收到 `presence.*` → 更新 store；收到 `event.created` → 按 action 失效对应 React Query 缓存；
 * - 收到 `doc.lock` → 记录"谁正在编辑哪份文档"；
 * - 页面重新可见（visibilitychange）时立即尝试重连；卸载时断开。
 */

import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeysForAction } from './eventBridge'
import RealtimeClient, { type PresenceMember, type RealtimeMessage, type RealtimeStatus } from './realtimeClient'
import { documentViewers, useRealtimeStore } from './realtimeStore'

export interface UseRealtimeResult {
  status: RealtimeStatus
  members: PresenceMember[]
  /** 上报当前用户在看/编辑哪份文档（`null` 表示离开文档页） */
  updatePresence: (documentId: number | null, mode: 'viewing' | 'editing' | null) => void
}

export function useRealtime(workspaceId: string | number | undefined): UseRealtimeResult {
  const queryClient = useQueryClient()
  const status = useRealtimeStore((s) => s.status)
  const members = useRealtimeStore((s) => s.members)
  const clientRef = useRef<RealtimeClient | null>(null)

  useEffect(() => {
    if (workspaceId === undefined || workspaceId === null || workspaceId === '') {
      return
    }
    const client = new RealtimeClient()
    clientRef.current = client

    const { setStatus, setMembers, setDocumentEditing, setParagraphLocks } = useRealtimeStore.getState()

    const handleMessage = (message: RealtimeMessage) => {
      const payload = message.payload ?? {}
      switch (message.type) {
        case 'presence.sync':
        case 'presence.join':
        case 'presence.leave':
        case 'presence.update': {
          const list = payload.members as PresenceMember[] | undefined
          if (Array.isArray(list)) setMembers(list)
          break
        }
        case 'doc.lock': {
          const documentId = Number(payload.document_id)
          if (!Number.isFinite(documentId)) break
          setDocumentEditing(
            documentId,
            payload.locked
              ? { user_id: (payload.user_id as number | null) ?? null, username: (payload.username as string | null) ?? null }
              : null,
          )
          break
        }
        case 'para.lock': {
          const documentId = Number(payload.document_id)
          const locks = payload.locks
          if (Number.isFinite(documentId) && Array.isArray(locks)) {
            setParagraphLocks(documentId, locks as never)
          }
          break
        }
        case 'event.created': {
          const action = String(payload.action ?? '')
          for (const prefix of queryKeysForAction(action)) {
            void queryClient.invalidateQueries({ queryKey: prefix })
          }
          break
        }
        default:
          break
      }
    }

    client.connect(workspaceId, {
      onMessage: handleMessage,
      onStatus: (next) => setStatus(next),
    })

    // 回到前台立即重连（移动端锁屏/切后台后 WS 常被系统断开）
    const onVisible = () => {
      if (document.visibilityState === 'visible') client.retryNow()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      client.close()
      clientRef.current = null
      setMembers([])
    }
  }, [workspaceId, queryClient])

  const updatePresence = useCallback((documentId: number | null, mode: 'viewing' | 'editing' | null) => {
    clientRef.current?.updatePresence(documentId, mode)
  }, [])

  return useMemo(() => ({ status, members, updatePresence }), [status, members, updatePresence])
}

/** 某文档当前的在线成员（编辑者在前） */
export function useDocumentViewers(documentId: number | null | undefined): PresenceMember[] {
  const members = useRealtimeStore((s) => s.members)
  return useMemo(() => (documentId ? documentViewers(members, documentId) : []), [members, documentId])
}

/** 某文档的段落锁快照（来自 para.lock 事件） */
export function useParagraphLockSnapshot(documentId: number | null | undefined) {
  return useRealtimeStore((s) => (documentId ? s.paragraphLocks[documentId] : undefined))
}

/** 某文档当前是否被他人编辑（来自 doc.lock 事件） */
export function useDocumentEditing(documentId: number | null | undefined) {
  return useRealtimeStore((s) =>
    documentId ? s.editingDocument[documentId] : undefined,
  )
}

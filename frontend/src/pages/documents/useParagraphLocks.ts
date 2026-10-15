/** 段落锁 hook —— 光标所在段落的锁获取/释放 + 他人锁定提示.
 *
 * 规则（与后端一致）：**同段互斥，不同段可并发**。
 * - 光标进入某段：若该段被他人锁住 → 只提示、不抢占；否则（防抖后）获取该段锁并释放上一段；
 * - 段落键为位置键 `p1`/`p2`…（基于已保存版本的位置，见 paragraphLocks.ts）；
 * - 他人锁来自实时通道（`para.lock`）与初次加载的接口，用于提示"谁在编辑第几段"。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { documentsApi } from '@/api/documents'
import type { ParagraphLockItem } from '@/api/documents'
import { paragraphIndexAtOffset } from './paragraphLocks'

const ACQUIRE_DEBOUNCE_MS = 400

export interface ParagraphLockState {
  /** 他人锁定的段落（含用户名） */
  othersLocks: ParagraphLockItem[]
  /** 我当前持有的段落键 */
  myKey: string | null
  /** 光标所在段落被他人锁住时的持锁人（用于即时提示） */
  blockedBy: { key: string; username: string } | null
  /** 光标/选择变化时上报（传 textarea 的 selectionStart） */
  onCaret: (offset: number) => void
  /** 释放我在本文档的全部段落锁（离开文档、保存后调用） */
  releaseAll: () => void
}

export function useParagraphLocks(options: {
  workspaceId: number
  docId: number
  content: string
  currentUserId?: number | string
  /** 实时通道推送的最新段落锁（docId 维度） */
  realtimeLocks?: ParagraphLockItem[]
  enabled?: boolean
}): ParagraphLockState {
  const { workspaceId, docId, content, currentUserId, realtimeLocks, enabled = true } = options

  const [locks, setLocks] = useState<ParagraphLockItem[]>([])
  const [myKey, setMyKey] = useState<string | null>(null)
  const [blockedBy, setBlockedBy] = useState<{ key: string; username: string } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const myKeyRef = useRef<string | null>(null)
  const contentRef = useRef(content)
  contentRef.current = content

  const isMine = useCallback(
    (lock: ParagraphLockItem) => String(lock.user_id) === String(currentUserId ?? ''),
    [currentUserId],
  )

  // 实时推送优先（最新快照）
  useEffect(() => {
    if (!enabled) return
    if (realtimeLocks) setLocks(realtimeLocks)
  }, [realtimeLocks, enabled])

  // 初次加载：拉取本文档已有段落锁
  useEffect(() => {
    if (!enabled || !Number.isFinite(docId)) return
    let alive = true
    documentsApi
      .listParagraphLocks(workspaceId, docId)
      .then((items) => {
        if (alive) setLocks(items)
      })
      .catch(() => {
        /* 拉取失败不影响编辑 */
      })
    return () => {
      alive = false
    }
  }, [workspaceId, docId, enabled])

  const othersLocks = locks.filter((lock) => !isMine(lock))

  const onCaret = useCallback(
    (offset: number) => {
      if (!enabled || !Number.isFinite(docId)) return
      const index = paragraphIndexAtOffset(contentRef.current, offset)
      if (index === null) return
      const key = `p${index}`

      const holder = othersLocks.find((lock) => lock.key === key)
      if (holder) {
        setBlockedBy({ key, username: holder.username })
        return
      }
      setBlockedBy(null)
      if (myKeyRef.current === key) return

      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        const previous = myKeyRef.current
        documentsApi
          .acquireParagraphLocks(workspaceId, docId, [key])
          .then((data) => {
            myKeyRef.current = key
            setMyKey(key)
            if (data.document_locks) setLocks(data.document_locks)
            if (previous && previous !== key) {
              // 释放上一段（保底：失败也不影响，服务端有 TTL）
              void documentsApi.releaseParagraphLocks(workspaceId, docId, [previous]).catch(() => {})
            }
          })
          .catch((err: unknown) => {
            const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
            setBlockedBy({ key, username: typeof detail === 'string' ? detail : '他人' })
          })
      }, ACQUIRE_DEBOUNCE_MS)
    },
    [enabled, docId, workspaceId, othersLocks],
  )

  const releaseAll = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    myKeyRef.current = null
    setMyKey(null)
    if (!Number.isFinite(docId)) return
    void documentsApi.releaseParagraphLocks(workspaceId, docId).catch(() => {})
  }, [workspaceId, docId])

  // 卸载（离开文档）时释放，避免留下过期锁
  useEffect(() => () => releaseAll(), [releaseAll])

  return { othersLocks, myKey, blockedBy, onCaret, releaseAll }
}

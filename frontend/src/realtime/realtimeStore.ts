/** 实时状态 store —— 连接状态 + 在线成员.
 *
 * 与 auth store 同为 zustand；这里**不持久化**（连接与在线状态都是瞬时的）。
 */

import { create } from 'zustand'
import type { ParagraphLockItem } from '@/api/documents'
import type { PresenceMember, RealtimeStatus } from './realtimeClient'

interface RealtimeState {
  status: RealtimeStatus
  /** 当前工作区在线成员 */
  members: PresenceMember[]
  /** 正在编辑某文档的成员（doc.lock 事件驱动，按文档 id 索引） */
  editingDocument: Record<number, { user_id: number | null; username: string | null } | undefined>
  /** 段落锁快照（para.lock 事件驱动，按文档 id 索引） */
  paragraphLocks: Record<number, ParagraphLockItem[] | undefined>
  setStatus: (status: RealtimeStatus) => void
  setMembers: (members: PresenceMember[]) => void
  setDocumentEditing: (documentId: number, info: { user_id: number | null; username: string | null } | null) => void
  setParagraphLocks: (documentId: number, locks: ParagraphLockItem[]) => void
  reset: () => void
}

export const useRealtimeStore = create<RealtimeState>((set) => ({
  status: 'idle',
  members: [],
  editingDocument: {},
  paragraphLocks: {},

  setStatus: (status) => set({ status }),
  setMembers: (members) => set({ members }),
  setDocumentEditing: (documentId, info) =>
    set((state) => {
      const next = { ...state.editingDocument }
      if (info) next[documentId] = info
      else delete next[documentId]
      return { editingDocument: next }
    }),
  setParagraphLocks: (documentId, locks) =>
    set((state) => ({ paragraphLocks: { ...state.paragraphLocks, [documentId]: locks } })),
  reset: () => set({ status: 'idle', members: [], editingDocument: {}, paragraphLocks: {} }),
}))

/** 某文档当前的查看/编辑者（编辑者在前） */
export function documentViewers(members: PresenceMember[], documentId: number): PresenceMember[] {
  return members
    .filter((m) => m.document_id === documentId)
    .sort((a, b) => (a.mode === 'editing' ? 0 : 1) - (b.mode === 'editing' ? 0 : 1) || a.user_id - b.user_id)
}

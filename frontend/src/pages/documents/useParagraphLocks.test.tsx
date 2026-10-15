/**
 * useParagraphLocks 测试 —— 同段互斥的行为在客户端的体现.
 *
 * 覆盖：初次加载拉取锁、光标进入空闲段落会（防抖后）获取锁、
 * 光标进入他人锁定段落只提示不抢占、离开时释放全部锁。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'

const listLocks = vi.fn()
const acquireLocks = vi.fn()
const releaseLocks = vi.fn()

vi.mock('@/api/documents', () => ({
  documentsApi: {
    listParagraphLocks: (...args: unknown[]) => listLocks(...args),
    acquireParagraphLocks: (...args: unknown[]) => acquireLocks(...args),
    releaseParagraphLocks: (...args: unknown[]) => releaseLocks(...args),
  },
}))

const { useParagraphLocks } = await import('./useParagraphLocks')

const DOC = '# 标题\n\n第一段\n\n第二段\n'

const lock = (key: string, userId: number, username: string) => ({
  document_id: 5,
  key,
  user_id: userId,
  username,
  elapsed_seconds: 1,
})

beforeEach(() => {
  listLocks.mockReset().mockResolvedValue([])
  acquireLocks.mockReset().mockResolvedValue({ locks: [], document_locks: [] })
  releaseLocks.mockReset().mockResolvedValue({ released: 0, document_locks: [] })
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useParagraphLocks', () => {
  it('初次加载拉取已有段落锁，并区分他人锁', async () => {
    listLocks.mockResolvedValue([lock('p2', 9, 'bob'), lock('p3', 7, 'me')])
    const { result } = renderHook(() =>
      useParagraphLocks({ workspaceId: 1, docId: 5, content: DOC, currentUserId: 7 }),
    )
    await waitFor(() => expect(result.current.othersLocks).toHaveLength(1))
    expect(result.current.othersLocks[0].username).toBe('bob')
  })

  it('光标进入空闲段落 → 防抖后获取该段锁', async () => {
    const { result } = renderHook(() =>
      useParagraphLocks({ workspaceId: 1, docId: 5, content: DOC, currentUserId: 7 }),
    )
    await waitFor(() => expect(listLocks).toHaveBeenCalled())

    const offset = DOC.indexOf('第一段') + 1
    act(() => result.current.onCaret(offset))
    await act(async () => {
      vi.advanceTimersByTime(500)
    })

    await waitFor(() => expect(acquireLocks).toHaveBeenCalledWith(1, 5, ['p2']))
  })

  it('光标进入他人锁定的段落 → 只提示不抢占', async () => {
    listLocks.mockResolvedValue([lock('p2', 9, 'bob')])
    const { result } = renderHook(() =>
      useParagraphLocks({ workspaceId: 1, docId: 5, content: DOC, currentUserId: 7 }),
    )
    await waitFor(() => expect(result.current.othersLocks).toHaveLength(1))

    const offset = DOC.indexOf('第一段') + 1
    act(() => result.current.onCaret(offset))
    await act(async () => {
      vi.advanceTimersByTime(500)
    })

    expect(acquireLocks).not.toHaveBeenCalled()
    await waitFor(() => expect(result.current.blockedBy).toEqual({ key: 'p2', username: 'bob' }))
  })

  it('releaseAll 释放本文档全部段落锁，卸载时也会释放', async () => {
    const { result, unmount } = renderHook(() =>
      useParagraphLocks({ workspaceId: 1, docId: 5, content: DOC, currentUserId: 7 }),
    )
    await waitFor(() => expect(listLocks).toHaveBeenCalled())

    act(() => result.current.releaseAll())
    await waitFor(() => expect(releaseLocks).toHaveBeenCalledWith(1, 5))

    unmount()
    await waitFor(() => expect(releaseLocks.mock.calls.length).toBeGreaterThanOrEqual(2))
  })
})

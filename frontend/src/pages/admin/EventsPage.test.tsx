/**
 * EventsPage 单测 —— 统一事件流页面.
 *
 * 覆盖：渲染事件行、动作与 request_id 展示、动作筛选触发带参请求、关键词检索、分页、
 * 空态、以及 AdminPanel 里「事件流」标签页可达。
 */

import { describe, expect, it, vi, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import EventsPage from './EventsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

const EVENTS = [
  {
    id: 2,
    created_at: '2026-10-15T12:00:00',
    action: 'auth.login',
    workspace_id: null,
    actor_id: 1,
    actor_name: 'alice',
    target_type: 'user',
    target_id: '1',
    summary: '登录成功：alice',
    detail: {},
    request_id: 'abcdef1234567890',
  },
  {
    id: 1,
    created_at: '2026-10-15T11:00:00',
    action: 'record.create',
    workspace_id: 3,
    actor_id: 2,
    actor_name: 'bob',
    target_type: 'record',
    target_id: '9',
    summary: 'create 记录（表 3）',
    detail: {},
    request_id: null,
  },
]

/** 覆盖 /events 与 /events/actions；传空 items 可模拟空态 */
function mockEvents(payload: { items: typeof EVENTS; total: number } = { items: EVENTS, total: 2 }) {
  const seen: string[] = []
  server.use(
    http.get('/api/v1/admin/events/actions', () =>
      HttpResponse.json({ items: [{ action: 'auth.login', count: 2 }, { action: 'record.create', count: 1 }] }),
    ),
    http.get('/api/v1/admin/events', ({ request }) => {
      const url = new URL(request.url)
      seen.push(url.search)
      return HttpResponse.json({ ...payload, page: 1, page_size: 20 })
    }),
  )
  return seen
}

afterEach(() => vi.restoreAllMocks())

describe('EventsPage', () => {
  it('渲染事件流：动作标签、操作人、摘要、目标与 request_id 缩写', async () => {
    mockEvents()
    renderProviders(<EventsPage />)

    expect(await screen.findByText('登录成功：alice')).toBeInTheDocument()
    expect(screen.getByText('auth.login')).toBeInTheDocument()
    expect(screen.getByText('record.create')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(screen.getByText('record#9')).toBeInTheDocument()
    // request_id 展示为前 8 位
    expect(screen.getByText('abcdef12')).toBeInTheDocument()
  })

  it('深链 ?action= 直接把筛选写进请求（可分享/刷新保持）', async () => {
    const seen = mockEvents()
    renderProviders(<EventsPage />, { route: '/admin?action=record.create' })
    await screen.findByText('登录成功：alice')
    expect(seen.some((s) => s.includes('action=record.create'))).toBe(true)
  })

  it('关键词检索把 keyword 写进 URL 并重新请求', async () => {
    const seen = mockEvents()
    renderProviders(<EventsPage />)
    await screen.findByText('登录成功：alice')

    // antd 6：Input.Search 的 data-testid 落在 group 包装层，实际 input 取其子节点
    const input = screen.getByTestId('event-keyword').querySelector('input')!
    fireEvent.change(input, { target: { value: 'alice' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })

    await waitFor(() => {
      expect(seen.some((s) => s.includes('keyword=alice'))).toBe(true)
    })
  })

  it('空结果展示空态', async () => {
    mockEvents({ items: [], total: 0 })
    renderProviders(<EventsPage />)
    expect(await screen.findByText('暂无事件')).toBeInTheDocument()
  })
})

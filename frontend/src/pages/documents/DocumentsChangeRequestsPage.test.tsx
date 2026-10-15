/**
 * DocumentsChangeRequestsPage 测试 —— 工作区级文档修改申请清单：
 * 列表渲染（含所属文档跳转）、scope 切换、空态、审核入口门控。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'

import type { DocumentChangeRequestItem } from '@/api/documents'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import DocumentsChangeRequestsPage from './DocumentsChangeRequestsPage'

const OPEN_CR: DocumentChangeRequestItem = {
  id: 7,
  workspace_id: 10,
  document_id: 2,
  document_title: '需求说明',
  title: '修改文档《需求说明》',
  description: '',
  change_summary: '',
  status: 'open',
  stale: false,
  base_version_number: 1,
  current_version_number: 1,
  proposed_size: 15,
  submitted_by_id: 2,
  reviewed_by_id: null,
  reviewed_at: null,
  review_comment: '',
  created_at: '2026-10-15T09:00:00',
  updated_at: '2026-10-15T09:00:00',
}

function renderPage(role: 'owner' | 'viewer' = 'owner') {
  server.use(
    http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({
        id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
        current_user_role: role,
      })),
  )
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/change-requests" element={<DocumentsChangeRequestsPage />} />
    </Routes>,
    { route: '/w/10/documents/change-requests', initialAuth: { user: mockUser, token: 'fake' } },
  )
}

describe('DocumentsChangeRequestsPage', () => {
  it('渲染待审核申请并展示所属文档与基准信息', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/document-change-requests', ({ request }) => {
        const scope = new URL(request.url).searchParams.get('scope')
        return HttpResponse.json({ items: scope === 'open' ? [OPEN_CR] : [], total: scope === 'open' ? 1 : 0 })
      }),
    )
    renderPage('owner')

    expect(await screen.findByText('修改文档《需求说明》')).toBeInTheDocument()
    expect(screen.getByText('需求说明')).toBeInTheDocument()
    expect(screen.getByText(/基准 v1 · 当前 v1/)).toBeInTheDocument()
    // owner 可审核
    expect(screen.getByTestId('dcr-merge-7')).toBeInTheDocument()
  })

  it('切换 scope 后按新筛选请求（空态提示）', async () => {
    const scopes: string[] = []
    server.use(
      http.get('/api/v1/workspaces/10/document-change-requests', ({ request }) => {
        const scope = new URL(request.url).searchParams.get('scope') ?? ''
        scopes.push(scope)
        return HttpResponse.json({ items: scope === 'open' ? [OPEN_CR] : [], total: 0 })
      }),
    )
    renderPage('owner')

    expect(await screen.findByText('修改文档《需求说明》')).toBeInTheDocument()
    fireEvent.click(screen.getByText('已通过'))

    await waitFor(() => expect(scopes).toContain('merged'))
    expect(await screen.findByText('暂无修改申请')).toBeInTheDocument()
  })

  it('viewer 只能查看与撤回自己的草稿，无审核入口', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/document-change-requests', () =>
        HttpResponse.json({ items: [OPEN_CR], total: 1 })),
    )
    renderPage('viewer') // mockUser.id=1，申请提交人是 2 → 非提交人

    expect(await screen.findByText('修改文档《需求说明》')).toBeInTheDocument()
    expect(screen.queryByTestId('dcr-merge-7')).toBeNull()
    expect(screen.queryByTestId('dcr-close-7')).toBeNull()
    expect(screen.queryByTestId('dcr-delete-7')).toBeNull()
    expect(screen.getByTestId('dcr-toggle-7')).toBeInTheDocument()
  })
})

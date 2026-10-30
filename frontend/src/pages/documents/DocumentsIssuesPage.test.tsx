/**
 * DocumentsIssuesPage 测试 —— 工作区级文档问题清单：
 * 列表渲染、状态筛选、详情抽屉（评论 + 关闭）、新建问题提交。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'

import type { DocumentIssueDetail, DocumentIssueItem } from '@/api/documents'
import { documentsApi } from '@/api/documents'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import DocumentsIssuesPage from './DocumentsIssuesPage'

const OPEN_ISSUE: DocumentIssueItem = {
  id: 11,
  workspace_id: 10,
  document_id: 2,
  document_title: '需求说明',
  title: '第三节口径与表格不一致',
  description: '第三节写的是含税，表格是不含税',
  category: 'data_error',
  status: 'open',
  created_by_id: 2,
  comment_count: 1,
  created_at: '2026-10-15T09:00:00',
  updated_at: '2026-10-15T09:00:00',
}

const DETAIL: DocumentIssueDetail = {
  ...OPEN_ISSUE,
  comments: [{ id: 3, content: '已确认，待更新', created_by_id: 1, created_at: '2026-10-15T09:30:00' }],
  events: [
    { id: 1, action: 'created', actor_id: 2, created_at: '2026-10-15T09:00:00' },
  ],
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
      <Route path="/w/:wid/documents/issues" element={<DocumentsIssuesPage />} />
    </Routes>,
    { route: '/w/10/documents/issues', initialAuth: { user: mockUser, token: 'fake' } },
  )
}

describe('DocumentsIssuesPage', () => {
  it('渲染问题列表：类别标签、所属文档与评论数', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/document-issues', () =>
        HttpResponse.json({ items: [OPEN_ISSUE], total: 1 })),
    )
    renderPage()

    expect(await screen.findByText('第三节口径与表格不一致')).toBeInTheDocument()
    expect(screen.getByText('数据异常')).toBeInTheDocument()
    expect(screen.getByText(/需求说明/)).toBeInTheDocument()
    expect(screen.getByLabelText('评论数 1')).toBeInTheDocument()
  })

  it('状态筛选切换后按新条件请求', async () => {
    const statuses: string[] = []
    server.use(
      http.get('/api/v1/workspaces/10/document-issues', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status') ?? ''
        statuses.push(status)
        return HttpResponse.json({ items: status === 'open' ? [OPEN_ISSUE] : [], total: 0 })
      }),
    )
    renderPage()

    expect(await screen.findByText('第三节口径与表格不一致')).toBeInTheDocument()
    fireEvent.click(screen.getByText('已关闭'))

    await waitFor(() => expect(statuses).toContain('closed'))
    expect(await screen.findByText('暂无问题')).toBeInTheDocument()
  })

  it('点击行打开详情抽屉：展示描述、评论与动态，可关闭问题', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/document-issues', () => HttpResponse.json({ items: [OPEN_ISSUE], total: 1 })),
      http.get('/api/v1/workspaces/10/document-issues/11', () => HttpResponse.json(DETAIL)),
    )
    const closeSpy = vi.spyOn(documentsApi, 'closeIssue').mockResolvedValue({ ...DETAIL, status: 'closed' })
    renderPage('owner')

    fireEvent.click(await screen.findByTestId('doc-issue-row-11'))

    expect(await screen.findByText('第三节写的是含税，表格是不含税')).toBeInTheDocument()
    expect(screen.getByText('已确认，待更新')).toBeInTheDocument()
    expect(screen.getByText(/创建了问题/)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('doc-issue-close'))
    await waitFor(() => expect(closeSpy).toHaveBeenCalledWith('10', 11))
    expect(await screen.findByText('问题已关闭')).toBeInTheDocument()
  })

  it('新建问题：选择文档并提交后携带 document_id', async () => {
    const createSpy = vi.spyOn(documentsApi, 'createIssue').mockResolvedValue(DETAIL)
    server.use(
      http.get('/api/v1/workspaces/10/document-issues', () => HttpResponse.json({ items: [], total: 0 })),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('doc-issue-create'))
    expect(await screen.findByText('新建文档问题')).toBeInTheDocument()

    // 选择所属文档（MSW 默认文档树含「需求说明」）
    const combo = await screen.findByTestId('doc-issue-document')
    fireEvent.mouseDown(combo)
    fireEvent.click(await screen.findByTitle('需求说明'))

    fireEvent.change(screen.getByPlaceholderText('一句话描述问题'), { target: { value: '标题与正文不符' } })
    fireEvent.click(screen.getByRole('button', { name: /提\s*交/ }))

    await waitFor(() => expect(createSpy).toHaveBeenCalled())
    expect(createSpy.mock.calls[0]![1]).toMatchObject({ document_id: 2, title: '标题与正文不符' })
  })
})

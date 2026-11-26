/** 工作区附件页测试（需求 0174）.
 *
 * 覆盖：列表渲染与归属文档、体检结果展示、owner 回收孤儿、viewer 不显示回收入口。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentAttachmentsPage from './DocumentAttachmentsPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { ResponsiveState } from '@/hooks/useResponsive'

const desktop: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', () => ({ useResponsive: () => desktop }))

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/attachments" element={<DocumentAttachmentsPage />} />
    </Routes>,
    { route: '/w/10/documents/attachments', initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

const LIST = {
  items: [
    {
      file_key: 'aaa.png',
      name: 'aaa.png',
      size: 2048,
      uploaded_at: 1760000000,
      document_id: 7,
      document_title: '图片文档',
      has_owner: true,
    },
    {
      file_key: 'orphan.png',
      name: 'orphan.png',
      size: 30,
      uploaded_at: 1760000100,
      document_id: null,
      document_title: null,
      has_owner: false,
    },
  ],
  total: 2,
}

describe('工作区附件页（需求 0174）', () => {
  let purged: Record<string, unknown> | null = null

  beforeEach(() => {
    purged = null
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/attachments', () => HttpResponse.json(LIST)),
      http.get('/api/v1/workspaces/:wid/capabilities', () => HttpResponse.json({ data_role: 'owner' })),
      http.post('/api/v1/workspaces/:wid/documents/attachments/scan', () =>
        HttpResponse.json({
          items: [
            { file_key: 'aaa.png', name: 'aaa.png', size: 2048, ref_count: 1, orphan: false },
            { file_key: 'orphan.png', name: 'orphan.png', size: 30, ref_count: 0, orphan: true },
          ],
          total: 2,
          orphan_count: 1,
          orphan_bytes: 30,
        }),
      ),
      http.post('/api/v1/workspaces/:wid/documents/attachments/purge', async ({ request }) => {
        purged = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          dry_run: false,
          orphan_count: 1,
          orphan_bytes: 30,
          removed_files: 1,
          removed_bytes: 30,
        })
      }),
    )
  })

  it('列出附件与归属文档，体检后标记孤儿并可回收', async () => {
    renderPage()
    expect(await screen.findByText('aaa.png')).toBeInTheDocument()
    expect(screen.getByText('图片文档')).toBeInTheDocument()
    expect(screen.getByText('未登记归属')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('attachment-scan'))
    expect(await screen.findByText(/1 个孤儿附件/)).toBeInTheDocument()
    expect(screen.getAllByText('孤儿').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByTestId('attachment-purge'))
    fireEvent.click(await screen.findByRole('button', { name: /^回\s*收$/ }))
    await waitFor(() => expect(purged).toEqual({ dry_run: false }))
  })

  it('viewer 不显示回收入口', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/capabilities', () => HttpResponse.json({ data_role: 'viewer' })),
    )
    renderPage()
    expect(await screen.findByText('aaa.png')).toBeInTheDocument()
    expect(screen.queryByTestId('attachment-purge')).toBeNull()
    expect(screen.getByTestId('attachment-scan')).toBeInTheDocument()
  })
})

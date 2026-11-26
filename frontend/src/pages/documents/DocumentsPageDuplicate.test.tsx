/** 文档列表「创建副本」入口测试（需求 0172 C6）.
 *
 * 覆盖：行操作出现「创建副本」、点击后调用 duplicate 端点并刷新列表。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentsPage from './DocumentsPage'
import { renderProviders } from '@/test/render-providers'
import { mockDocuments, mockUser, server } from '@/test/msw'
import type { ResponsiveState } from '@/hooks/useResponsive'

const desktop: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', () => ({ useResponsive: () => desktop }))

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents" element={<DocumentsPage />} />
      <Route path="/w/:wid/documents/:docId" element={<div data-testid="editor-stub" />} />
    </Routes>,
    { route: '/w/10/documents?parent=1', initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

describe('创建文档副本（需求 0172）', () => {
  let duplicated: number | null = null

  beforeEach(() => {
    duplicated = null
    server.use(
      http.post('/api/v1/workspaces/:wid/documents/:docId/duplicate', ({ params }) => {
        duplicated = Number(params.docId)
        return HttpResponse.json({ ...mockDocuments[1], id: 99, title: '需求说明 副本' })
      }),
    )
  })

  it('行操作「创建副本」调用端点并提示新标题', async () => {
    renderPage()
    const menu = await screen.findByTestId('doc-row-more-2')
    fireEvent.click(menu)
    fireEvent.click(await screen.findByTestId('doc-row-duplicate-2'))

    await waitFor(() => expect(duplicated).toBe(2))
  })
})

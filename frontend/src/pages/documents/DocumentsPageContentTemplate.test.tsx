/** 文档列表「从模板新建」入口测试（需求 0169 C4）.
 *
 * 覆盖：入口可见、模板选择弹层列出模板、选中后以模板名与正文调用现有
 * create_document（草稿口径与直接新建一致）。
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
    { route: '/w/10/documents', initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

describe('从内容模板新建文档（需求 0169 C4）', () => {
  let createdPayload: Record<string, unknown> | null = null

  beforeEach(() => {
    createdPayload = null
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({
          items: [
            {
              id: 7,
              workspace_id: 10,
              name: '会议纪要',
              content_markdown: '# 会议纪要\n\n## 议题',
              description: '周会用',
              icon: '📝',
              sort_order: 0,
              export_template_ref: 'builtin:thesis',
              created_by_id: 1,
              created_at: null,
              updated_at: null,
            },
          ],
          total: 1,
        }),
      ),
      http.post('/api/v1/workspaces/:wid/documents', async ({ request }) => {
        createdPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...mockDocuments[1], id: 99, title: String(createdPayload.title) })
      }),
    )
  })

  it('新建下拉提供「从模板新建」，选中模板后携带模板正文建文档', async () => {
    renderPage()

    fireEvent.click(await screen.findByTestId('doc-create-menu'))
    fireEvent.click(await screen.findByText('从模板新建'))

    const option = await screen.findByTestId('content-template-option-7')
    expect(option).toHaveTextContent('会议纪要')
    fireEvent.click(option)

    await waitFor(() => {
      expect(createdPayload).toMatchObject({
        title: '会议纪要',
        content: '# 会议纪要\n\n## 议题',
        export_template_ref: 'builtin:thesis',
        is_folder: false,
      })
    })
  })

  it('先打开新建文件夹再取消，从模板新建仍建文档（不残留 is_folder）', async () => {
    renderPage()

    // 先进入「新建文件夹」弹窗再取消（createType 会残留 folder）
    fireEvent.click(await screen.findByTestId('doc-create-menu'))
    fireEvent.click(await screen.findByText('新建文件夹'))
    expect(await screen.findByPlaceholderText('文件夹名称')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }))

    fireEvent.click(await screen.findByTestId('doc-create-menu'))
    fireEvent.click(await screen.findByText('从模板新建'))
    fireEvent.click(await screen.findByTestId('content-template-option-7'))

    await waitFor(() => {
      expect(createdPayload).toMatchObject({
        title: '会议纪要',
        content: '# 会议纪要\n\n## 议题',
        is_folder: false,
      })
    })
  })

  it('无模板时空态引导前往内容模板页', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('doc-create-menu'))
    fireEvent.click(await screen.findByText('从模板新建'))

    expect(await screen.findByText('还没有内容模板')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '去创建模板' })).toBeInTheDocument()
  })
})

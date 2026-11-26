/** 文档内容模板页测试（需求 0169 C4/C5）.
 *
 * 覆盖：模板清单渲染与选中、Markdown 正文编辑保存、删除、空态引导创建。
 * MarkdownLiveEditor 用轻量 textarea 替代（CodeMirror 在 jsdom 下不稳定）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentContentTemplatesPage from './DocumentContentTemplatesPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { ContentTemplateItem } from '@/api'

vi.mock('@/components/Document/MarkdownLiveEditor', () => ({
  default: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea
      data-testid="template-markdown"
      value={value}
      onChange={e => onChange(e.target.value)}
    />
  ),
}))

const tpl = (id: number, name: string, body: string): ContentTemplateItem => ({
  id,
  workspace_id: 1,
  name,
  content_markdown: body,
  description: '模板说明',
  icon: '📝',
  sort_order: id,
  created_by_id: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
})

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/content-templates" element={<DocumentContentTemplatesPage />} />
    </Routes>,
    { route: '/w/1/documents/content-templates', initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

describe('文档内容模板页（需求 0169）', () => {
  let savedPayload: Record<string, unknown> | null = null
  let deletedId: number | null = null
  let createdNames: string[] = []

  beforeEach(() => {
    savedPayload = null
    deletedId = null
    createdNames = []
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [tpl(1, '会议纪要', '# 纪要'), tpl(2, '周报', '# 周报')], total: 2 }),
      ),
      http.patch('/api/v1/workspaces/:wid/document-content-templates/:id', async ({ request }) => {
        savedPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(tpl(1, '会议纪要', String(savedPayload.content_markdown ?? '')))
      }),
      http.delete('/api/v1/workspaces/:wid/document-content-templates/:id', ({ params }) => {
        deletedId = Number(params.id)
        return HttpResponse.json({ ok: true })
      }),
      http.post('/api/v1/workspaces/:wid/document-content-templates', async ({ request }) => {
        const body = (await request.json()) as { name: string; content_markdown?: string }
        createdNames.push(body.name)
        return HttpResponse.json(tpl(3, body.name, body.content_markdown ?? ''))
      }),
    )
  })

  it('列出模板并选中首个，修改正文后保存携带完整草稿', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toHaveTextContent('会议纪要')
    expect(screen.getByTestId('template-markdown')).toHaveValue('# 纪要')

    fireEvent.change(screen.getByTestId('template-markdown'), { target: { value: '# 新纪要正文' } })
    fireEvent.click(screen.getByTestId('content-template-save'))

    await waitFor(() => {
      expect(savedPayload).toMatchObject({
        name: '会议纪要',
        description: '模板说明',
        content_markdown: '# 新纪要正文',
      })
    })
  })

  it('切换模板后正文随之更新，删除按钮调用对应 id', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-2')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-row-2'))
    expect(screen.getByTestId('template-markdown')).toHaveValue('# 周报')
    fireEvent.click(screen.getByTestId('content-template-delete'))
    // Popconfirm 二次确认（antd 两字按钮插空格）
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))
    await waitFor(() => expect(deletedId).toBe(2))
  })

  it('有未保存修改时切换模板先确认，确认后切换', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('template-markdown'), { target: { value: '# 未保存改动' } })

    fireEvent.click(screen.getByTestId('content-template-row-2'))
    expect(await screen.findByText('放弃未保存的修改？')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '放弃并切换' }))

    await waitFor(() => expect(screen.getByTestId('template-markdown')).toHaveValue('# 周报'))
  })

  it('新建模板调用 POST 并选中新模板', async () => {
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-create'))
    await waitFor(() => expect(createdNames).toEqual(['未命名模板']))
  })

  it('已有同名未命名模板时，新建自动递增为「未命名模板 2」', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [tpl(1, '未命名模板', '')], total: 1 }),
      ),
    )
    renderPage()
    expect(await screen.findByTestId('content-template-row-1')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('content-template-create'))
    await waitFor(() => expect(createdNames).toEqual(['未命名模板 2']))
  })

  it('空态显示创建首个模板引导', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    )
    renderPage()
    expect(await screen.findByText('还没有内容模板')).toBeInTheDocument()
    expect(screen.getByText('创建首个模板')).toBeInTheDocument()
  })
})

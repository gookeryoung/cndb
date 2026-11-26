/** 模板页容器测试（ADR 0177 C3 / D4）.
 *
 * 覆盖：`?kind=export|content` 分区切换、缺省与脏值回落导出模板、
 * 以及 `resolveTemplateKind` 的纯函数口径。两个面板各自的数据请求用 MSW 短路。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { http, HttpResponse } from 'msw'

import DocumentTemplatesPage, { resolveTemplateKind } from './DocumentTemplatesPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'

vi.mock('@/components/Document/MarkdownLiveEditor', () => ({
  default: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea data-testid="template-markdown" value={value} onChange={e => onChange(e.target.value)} />
  ),
}))

function renderRoute(route: string) {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/templates" element={<DocumentTemplatesPage />} />
    </Routes>,
    { route, initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

beforeEach(() => {
  server.use(
    http.get('/api/v1/workspaces', () =>
      HttpResponse.json([{ id: 1, name: '模板工作区', modules: ['documents'], current_user_role: 'owner' }]),
    ),
    http.get('/api/v1/workspaces/:wid/documents/templates', () =>
      HttpResponse.json({ items: [], total: 0, default_ref: 'builtin:research' }),
    ),
    http.get('/api/v1/workspaces/:wid/document-content-templates', () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  )
})

describe('resolveTemplateKind', () => {
  it('只认 content，缺省与脏值都按导出模板', () => {
    expect(resolveTemplateKind('content')).toBe('content')
    expect(resolveTemplateKind('export')).toBe('export')
    expect(resolveTemplateKind(null)).toBe('export')
    expect(resolveTemplateKind('CONTENT')).toBe('export')
    expect(resolveTemplateKind('graph')).toBe('export')
  })
})

describe('DocumentTemplatesPage（一个入口两个分区）', () => {
  it('无 kind 参数时渲染导出模板分区', async () => {
    renderRoute('/w/1/documents/templates')
    expect(await screen.findByTestId('document-templates-page')).toBeInTheDocument()
    expect(await screen.findByTestId('template-list')).toBeInTheDocument()
    expect(screen.queryByTestId('document-content-templates-page')).not.toBeInTheDocument()
  })

  it('?kind=content 时渲染内容模板分区', async () => {
    renderRoute('/w/1/documents/templates?kind=content')
    expect(await screen.findByTestId('document-content-templates-page')).toBeInTheDocument()
    expect(await screen.findByTestId('content-template-list')).toBeInTheDocument()
    expect(screen.queryByTestId('document-templates-page')).not.toBeInTheDocument()
  })

  it('?kind=export 与脏值都渲染导出模板分区（不因非法值空白）', async () => {
    renderRoute('/w/1/documents/templates?kind=bogus')
    expect(await screen.findByTestId('document-templates-page')).toBeInTheDocument()
    expect(await screen.findByTestId('template-list')).toBeInTheDocument()
  })
})

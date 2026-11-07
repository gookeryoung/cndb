/** 复用模块只读页测试（ADR 0118 P1）：详情 / 版本切换 / 参数预览 / 无权兜底 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import LibraryModulePage from './LibraryModulePage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

vi.mock('./PreviewCanvas', () => ({
  default: function PreviewCanvasStub({ ir }: { ir: { nodes: unknown[] } | null }) {
    return <div data-testid="preview-canvas-stub">节点:{(ir?.nodes.length ?? 0)}</div>
  },
}))

const AUTH = { initialAuth: { user: null, token: 'fake' } }

const DETAIL = {
  id: 7,
  module_key: 'flange',
  name: '法兰模块',
  description: '标准法兰',
  visibility: 'public',
  owner_workspace_id: 10,
  is_archived: false,
  version_count: 2,
  latest_version: 2,
  params: [{ name: 'd', default: 10 }],
  updated_at: '2026-10-02T08:00:00Z',
  can_manage: false,
  versions: [
    {
      id: 72, version_number: 2, content_hash: 'h2', bundle_hash: 'b2',
      comment: '加厚', created_by_id: 1, created_at: '2026-10-02T08:00:00Z',
    },
    {
      id: 71, version_number: 1, content_hash: 'h1', bundle_hash: 'b1',
      comment: '', created_by_id: 1, created_at: '2026-10-01T08:00:00Z',
    },
  ],
}

function useHandlers() {
  server.use(
    http.get('/api/v1/workspaces/10/design-library/modules/7', () => HttpResponse.json(DETAIL)),
    http.get('/api/v1/workspaces/10/design-library/modules/7/versions/:version', ({ params }) =>
      HttpResponse.json({
        ...DETAIL.versions.find(item => item.version_number === Number(params.version)),
        content: Number(params.version) === 2 ? 'cyl(d = 20, h = 2)' : 'cyl(d = 10, h = 2)',
        params: [{ name: 'd', default: Number(params.version) === 2 ? 20 : 10 }],
        files: [{ file_key: 'boss', kind: 'part', content_hash: 'h' }],
      })),
    http.post('/api/v1/workspaces/10/design-library/modules/7/versions/:version/preview', () =>
      HttpResponse.json({ ok: true, ir: { nodes: [{ op: 'cyl' }] }, diagnostics: [] })),
  )
}

function renderPage(route = '/w/10/design/library/7') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/design/library/:moduleId" element={<LibraryModulePage />} />
    </Routes>,
    { route, ...AUTH },
  )
}

describe('LibraryModulePage 只读页', () => {
  it('展示模块头、锁定版本、DSL 原文与预览', async () => {
    useHandlers()
    renderPage()

    expect(await screen.findByText('法兰模块')).toBeInTheDocument()
    expect(screen.getByText('flange')).toBeInTheDocument()
    expect(screen.getByText('公开')).toBeInTheDocument()
    expect(await screen.findByTestId('library-dsl-content')).toHaveTextContent('cyl(d = 20, h = 2)')
    expect(await screen.findByTestId('preview-canvas-stub')).toHaveTextContent('节点:1')
    expect(screen.getByText('依赖：')).toBeInTheDocument()
    expect(screen.getByText('boss')).toBeInTheDocument()
  })

  it('切换历史版本后重新拉取原文与预览', async () => {
    useHandlers()
    renderPage()

    expect(await screen.findByTestId('library-dsl-content')).toHaveTextContent('d = 20')
    const selector = screen.getByRole('combobox')
    fireEvent.mouseDown(selector)
    fireEvent.click(await screen.findByText('v1'))
    await waitFor(() => {
      expect(screen.getByTestId('library-dsl-content')).toHaveTextContent('d = 10')
    })
  })

  it('模块不存在 / 无权查看时显示空态', async () => {
    server.use(http.get('/api/v1/workspaces/10/design-library/modules/7', () =>
      HttpResponse.json({ code: 'design_library_module_not_found', detail: '不存在' }, { status: 404 })))
    renderPage()

    expect(await screen.findByTestId('library-detail-error')).toBeInTheDocument()
    expect(screen.getByText('模块不存在或无权查看')).toBeInTheDocument()
  })
})

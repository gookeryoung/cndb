/** DesignsPage 测试 —— 设计模块根页只负责默认选中 / 空态（ADR 0109 D1 / D3 / C5）
 *
 * Content 不再承载产品列表与结构树（已移入侧栏）：有设计时 replace 到最近更新的编辑器；
 * 无设计时展示引导空态；清单失败时展示错误空态；页面不再出现 cn-qc-split 双栏与页头。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import DesignsPage from './DesignsPage'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type { DesignListItem } from '@/api'

const AUTH = { initialAuth: { user: null, token: 'fake' } }

const DESIGN: DesignListItem = {
  id: 20,
  workspace_id: 10,
  title: '法兰板',
  description: '示例结构',
  kind: 'assembly',
  file_key: 'flange-plate',
  folder: '',
  dependencies_stale: false,
  version_count: 3,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-02T08:00:00Z',
}

function EditorStub() {
  const loc = useLocation()
  return <div data-testid="editor-stub">{loc.pathname}</div>
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/design" element={<DesignsPage />} />
      <Route path="/w/:wid/design/:designId" element={<EditorStub />} />
    </Routes>,
    { route: '/w/10/design', ...AUTH },
  )
}

function useListHandler(items: DesignListItem[]) {
  server.use(http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json(items)))
}

describe('设计根页 · 默认选中最近更新的产品（ADR 0109 D3 / C5）', () => {
  it('有设计时 replace 到最近更新的产品编辑器', async () => {
    useListHandler([
      DESIGN,
      { ...DESIGN, id: 21, title: '最新件', updated_at: '2026-10-05T08:00:00Z' },
    ])
    renderPage()

    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/21')
  })

  it('Content 为空态 / 重定向占位，不再渲染双栏与页头', async () => {
    useListHandler([])
    const { container } = renderPage()

    expect(await screen.findByTestId('designs-empty')).toBeInTheDocument()
    expect(container.querySelector('.cn-qc-split')).toBeNull()
    expect(container.querySelector('.cn-page-head')).toBeNull()
    expect(screen.queryByTestId('design-products-box')).toBeNull()
    expect(screen.queryByTestId('design-outline-box')).toBeNull()
  })

  it('无设计时保留根页并引导从侧栏新建', async () => {
    useListHandler([])
    renderPage()

    expect(await screen.findByText('还没有结构设计，从左侧产品列表新建第一个设计')).toBeInTheDocument()
    expect(screen.getByText('新建后可直接在右侧编辑 DSL 并实时预览 3D 结构。')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('editor-stub')).toBeNull())
  })

  it('viewer 空态只提示没有设计，不引导新建', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json([])),
      http.get('/api/v1/workspaces/10', () => HttpResponse.json({
        ...mockWorkspace, id: 10, current_user_role: 'viewer',
      })),
    )
    renderPage()

    expect(await screen.findByText('当前工作区还没有结构设计')).toBeInTheDocument()
    expect(screen.queryByText('新建后可直接在右侧编辑 DSL 并实时预览 3D 结构。')).toBeNull()
  })

  it('清单加载失败时展示错误空态且不跳转', async () => {
    server.use(http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json(
      { detail: 'boom' }, { status: 500 },
    )))
    renderPage()

    expect(await screen.findByText('设计清单加载失败，请稍后重试')).toBeInTheDocument()
    expect(screen.queryByTestId('editor-stub')).toBeNull()
  })
})

/** DesignsPage 测试 —— 列表展示 / 新建（示例模板）/ 改名 / 删除 / viewer 只读（ADR 0079 §7）. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import DesignsPage, { DEFAULT_DESIGN_CONTENT } from './DesignsPage'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type { DesignDetail, DesignListItem } from '@/api'

const AUTH = { initialAuth: { user: null, token: 'fake' } }

const DESIGN: DesignListItem = {
  id: 20,
  workspace_id: 10,
  title: '法兰板',
  description: '示例结构',
  version_count: 3,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-02T08:00:00Z',
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/design" element={<DesignsPage />} />
      <Route path="/w/:wid/design/:designId" element={<div data-testid="editor-stub">编辑器</div>} />
    </Routes>,
    { route: '/w/10/design', ...AUTH },
  )
}

/** 列表端点（默认 handler 未覆盖 designs，须逐用例注册） */
function useListHandler(items: DesignListItem[] = [DESIGN]) {
  server.use(http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json(items)))
}

function makeDetail(id: number, title: string, content: string): DesignDetail {
  return {
    id,
    workspace_id: 10,
    title,
    description: '',
    version_count: 1,
    created_at: '2026-10-01T08:00:00Z',
    updated_at: '2026-10-01T08:00:00Z',
    content,
    compiled: {},
    version_number: 1,
  }
}

describe('DesignsPage 列表与管理', () => {
  it('展示设计名称、描述与版本数', async () => {
    useListHandler()
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    expect(screen.getByText(/示例结构/)).toBeInTheDocument()
    expect(screen.getByText(/v3/)).toBeInTheDocument()
  })

  it('空列表展示空态', async () => {
    useListHandler([])
    renderPage()

    expect(await screen.findByText('还没有结构设计')).toBeInTheDocument()
  })

  it('新建设计：以示例模板为初始内容并跳转编辑器', async () => {
    useListHandler()
    let created: { title?: string; content?: string; description?: string } | undefined
    server.use(http.post('/api/v1/workspaces/10/designs', async ({ request }) => {
      const body = await request.json() as { title?: string; content?: string; description?: string }
      created = body
      return HttpResponse.json(makeDetail(77, '垫块', body.content ?? ''), { status: 201 })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新建设计/ }))
    fireEvent.change(await screen.findByPlaceholderText('如：法兰板'), { target: { value: '垫块' } })
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(await screen.findByTestId('editor-stub')).toBeInTheDocument()
    await waitFor(() => expect(created).toBeDefined())
    expect(created!.title).toBe('垫块')
    // 创建即带 ADR §2 法兰板模板（后端编译过才落 v1）
    expect(created!.content).toBe(DEFAULT_DESIGN_CONTENT)
  })

  it('viewer 只读：隐藏新建与删除，保留打开', async () => {
    useListHandler()
    server.use(http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({ ...mockWorkspace, id: 10, current_user_role: 'viewer' })))
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建设计/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编\s*辑/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删\s*除/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /打\s*开/ })).toBeInTheDocument()
  })

  it('改名走更新接口', async () => {
    useListHandler()
    let updated: { title?: string; description?: string } | undefined
    server.use(http.put('/api/v1/workspaces/10/designs/20', async ({ request }) => {
      updated = await request.json() as typeof updated
      return HttpResponse.json({ ...DESIGN, title: updated?.title ?? DESIGN.title })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ }))
    fireEvent.change(await screen.findByDisplayValue('法兰板'), { target: { value: '盖板' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(updated).toEqual({ title: '盖板', description: '示例结构' }))
  })

  it('删除需二次确认并调用删除接口', async () => {
    useListHandler()
    let deleted = false
    server.use(http.delete('/api/v1/workspaces/10/designs/20', () => {
      deleted = true
      return new HttpResponse(null, { status: 204 })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /删\s*除/ }))
    // Popconfirm 为 portal 渲染，等待确认按钮出现后再点击
    const confirmButtons = await screen.findAllByRole('button', { name: /删\s*除/ })
    fireEvent.click(confirmButtons[confirmButtons.length - 1]!)
    await waitFor(() => expect(deleted).toBe(true))
  })
})

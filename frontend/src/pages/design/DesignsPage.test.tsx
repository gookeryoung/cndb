/** DesignsPage 测试 —— 设计管理页：列表 / 新建（三级装配示例模板）/ 改名 / 删除 / viewer 只读
 *  （ADR 0084 D5；装配结构树已迁至侧栏，由 DesignStructureNav 覆盖）. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import DesignsPage, { DEFAULT_DESIGN_CONTENT, DEFAULT_PART_CONTENT } from './DesignsPage'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type { DesignDetail, DesignListItem } from '@/api'

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

/** 编辑器路由桩：展示 pathname + query，供断言跳转（0083 D7） */
function EditorStub() {
  const loc = useLocation()
  return <div data-testid="editor-stub">{loc.pathname}{loc.search}</div>
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

/** 列表端点（默认 handler 返回空列表，须逐用例注册） */
function useListHandler(items: DesignListItem[] = [DESIGN]) {
  server.use(http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json(items)))
}

function makeDetail(id: number, title: string, content: string): DesignDetail {
  return {
    ...DESIGN,
    id,
    title,
    version_count: 1,
    content,
    content_hash: 'hash',
    version_number: 1,
  }
}

describe('设计管理页（0084 D5）', () => {
  it('展示设计名称、描述、版本数与更新时间', async () => {
    useListHandler()
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    expect(screen.getByText(/示例结构/)).toBeInTheDocument()
    expect(screen.getByText(/v3/)).toBeInTheDocument()
    expect(screen.getByTestId('design-row-20')).toBeInTheDocument()
  })

  it('空列表展示空态', async () => {
    useListHandler([])
    renderPage()

    expect(await screen.findByText('还没有结构设计')).toBeInTheDocument()
  })

  it('打开设计进入编辑器', async () => {
    useListHandler()
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /打\s*开/ }))
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20')
  })

  it('新建设计：以三级装配示例模板为初始内容并跳转编辑器', async () => {
    useListHandler()
    let created: { title?: string; content?: string; description?: string } | undefined
    server.use(http.post('/api/v1/workspaces/10/designs', async ({ request }) => {
      const body = await request.json() as { title?: string; content?: string; description?: string }
      created = body
      return HttpResponse.json(makeDetail(77, '小车', body.content ?? ''), { status: 201 })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新建设计/ }))
    fireEvent.change(await screen.findByPlaceholderText('如：法兰板'), { target: { value: '小车' } })
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(await screen.findByTestId('editor-stub')).toBeInTheDocument()
    await waitFor(() => expect(created).toBeDefined())
    expect(created!.title).toBe('小车')
    expect(created!.content).toBe(DEFAULT_DESIGN_CONTENT)
  })

  it('默认模板含系统 / 组件 / 零件三级装配写法（0084 C4）', () => {
    expect(DEFAULT_DESIGN_CONTENT).toContain('system rover {')
    expect(DEFAULT_DESIGN_CONTENT).toContain('module chassis(')
    expect(DEFAULT_DESIGN_CONTENT).toContain('module wheel(')
    expect(DEFAULT_DESIGN_CONTENT).toContain('sphere(r = 14)')
  })

  it('新建零件：kind/folder/file_key 进入请求并使用零件模板（ADR 0086 C1）', async () => {
    useListHandler()
    let created: Record<string, unknown> | undefined
    server.use(http.post('/api/v1/workspaces/10/designs', async ({ request }) => {
      created = await request.json() as Record<string, unknown>
      return HttpResponse.json(makeDetail(78, '垫块', created?.content as string ?? ''), { status: 201 })
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新建设计/ }))
    fireEvent.change(await screen.findByPlaceholderText('如：法兰板'), { target: { value: '垫块' } })
    fireEvent.mouseDown(screen.getAllByText('装配（系统 / 组件装配声明）')[0]!)
    fireEvent.click(await screen.findByText('零件（顶层参数 + 零件几何）'))
    fireEvent.change(screen.getByPlaceholderText('如：parts/rover'), { target: { value: 'parts/demo' } })
    fireEvent.change(screen.getByPlaceholderText('缺省由名称生成'), { target: { value: 'demo_block' } })
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(await screen.findByTestId('editor-stub')).toBeInTheDocument()
    await waitFor(() => expect(created).toBeDefined())
    expect(created!.kind).toBe('part')
    expect(created!.folder).toBe('parts/demo')
    expect(created!.file_key).toBe('demo_block')
    expect(created!.content).toBe(DEFAULT_PART_CONTENT)
  })

  it('列表展示类型 / 目录 / 依赖陈旧标记（ADR 0086 C4）', async () => {
    useListHandler([{ ...DESIGN, kind: 'part', folder: 'parts/demo', dependencies_stale: true }])
    renderPage()

    expect(await screen.findByText('零件')).toBeInTheDocument()
    expect(screen.getByText('parts/demo')).toBeInTheDocument()
    expect(screen.getByTestId('design-list-stale-20')).toBeInTheDocument()
    expect(screen.getByText('flange-plate')).toBeInTheDocument()
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

/** DesignsPage 测试 —— 结构树（默认页）/ 大纲懒加载 / 源行跳转 / 新建 / 改名 / 删除（ADR 0083、0079 §7）. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route, useLocation } from 'react-router-dom'
import DesignsPage, { DEFAULT_DESIGN_CONTENT } from './DesignsPage'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type { DesignDetail, DesignListItem, DesignOutlineNode } from '@/api'

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

/** 编辑器路由桩：展示 pathname + query，供断言 ?line= 定位（0083 D7） */
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

/** 大纲端点：法兰板样例（组件 plate → 差集分组 → 立方体 + 圆柱） */
const OUTLINE: DesignOutlineNode[] = [
  {
    kind: 'assembly', name: 'plate', line: 10, col: 1,
    children: [{
      kind: 'group', op: 'difference', line: 11, col: 3,
      children: [
        { kind: 'part', primitive: 'box', line: 12, col: 5 },
        { kind: 'part', primitive: 'cyl', line: 14, col: 7 },
      ],
    }],
  },
]

function useOutlineHandler(source: 'compiled' | 'content' = 'compiled') {
  server.use(http.get('/api/v1/workspaces/10/designs/20/outline', () => HttpResponse.json({
    design_id: 20,
    version_number: 3,
    outline: { children: OUTLINE },
    source,
  })))
}

/** 点击树节点的展开箭头。
 *  antd Tree 展开带 collapse motion（motionDeadline=500ms），动画期间 rc-tree 的
 *  listChanging 会吞掉后续展开点击，因此每次点击前先等这一窗口过去。 */
async function clickSwitcher(testId: string) {
  // 等展开动画窗口过去，再点下一层的展开箭头
  await new Promise((resolve) => setTimeout(resolve, 600))
  const switcher = screen.getByTestId(testId)
    .closest('.ant-tree-treenode')
    ?.querySelector('.ant-tree-switcher')
  expect(switcher).toBeTruthy()
  fireEvent.click(switcher as Element)
}

/** 展开节点并等待其进入展开态 */
async function expandNode(testId: string) {
  await clickSwitcher(testId)
  await waitFor(() => {
    expect(screen.getByTestId(testId).closest('.ant-tree-treenode')?.getAttribute('aria-expanded')).toBe('true')
  })
}

describe('DesignsPage 结构树（0083）', () => {
  it('展开设计懒加载大纲并展示组件 / 分组 / 零件与源行', async () => {
    useListHandler()
    useOutlineHandler()
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    await expandNode('design-node-20')
    expect(await screen.findByText('plate')).toBeInTheDocument()

    await expandNode('design-outline-node-design-20-0')
    expect(await screen.findByText('差集')).toBeInTheDocument()

    await expandNode('design-outline-node-design-20-0-0')
    expect(await screen.findByText('立方体')).toBeInTheDocument()
    expect(screen.getByText('零件 · 第 12 行')).toBeInTheDocument()
    expect(screen.getByText('圆柱')).toBeInTheDocument()
    // 组件元信息：装配层级 + 零件计数（前端按 children 派生）
    expect(screen.getByText('组件 · 第 10 行 · 2 个零件')).toBeInTheDocument()
  })

  it('点击零件节点进入编辑器并定位源行（?line=）', async () => {
    useListHandler()
    useOutlineHandler()
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    await expandNode('design-node-20')
    await screen.findByText('plate')
    await expandNode('design-outline-node-design-20-0')
    await screen.findByText('差集')
    await expandNode('design-outline-node-design-20-0-0')
    const boxNode = await screen.findByText('立方体')

    fireEvent.click(boxNode)
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20?line=12')
  })

  it('历史快照派生（source=content）在设计节点标注', async () => {
    useListHandler()
    useOutlineHandler('content')
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    await expandNode('design-node-20')
    expect(await screen.findByText('历史快照派生')).toBeInTheDocument()
  })

  it('空大纲的设计节点不可展开', async () => {
    useListHandler([{ ...DESIGN, id: 21, title: '空白设计' }])
    server.use(http.get('/api/v1/workspaces/10/designs/21/outline', () => HttpResponse.json({
      design_id: 21, version_number: 1, outline: { children: [] }, source: 'compiled',
    })))
    renderPage()

    expect(await screen.findByText('空白设计')).toBeInTheDocument()
    await clickSwitcher('design-node-21')
    // 大纲为空后节点降级为叶子：展开箭头变 noop，且不渲染任何大纲子节点
    await waitFor(() => {
      const node = screen.getByTestId('design-node-21').closest('.ant-tree-treenode')
      expect(node?.querySelector('.ant-tree-switcher-noop')).toBeTruthy()
    })
    expect(screen.queryByTestId(/design-outline-node-design-21-/)).toBeNull()
  })
})

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
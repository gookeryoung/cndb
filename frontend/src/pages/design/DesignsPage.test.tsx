/** DesignsPage 测试 —— 「设计结构」根页左右分栏（ADR 0109 D1 / D2 / D3）
 *
 * 覆盖：页头 + 双栏骨架、左栏可选列表（筛选 / 选中 / 取消 / 动作 / viewer 门控）、
 * 右栏装配树（默认选中最近更新 / 懒加载 / 回落 / 空态 / 失败重试 / ?line= 定位）、
 * 以及新建 / 改名 / 删除主流程回归（ADR 0084 D5、ADR 0103 C8）。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
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

/** 装配大纲 fixture：系统 → 组件 → 零件 + 系统直属零件（ADR 0084 §9） */
const OUTLINE = {
  design_id: 20,
  version_number: 3,
  source: 'compiled' as const,
  outline: {
    children: [{
      kind: 'system',
      name: 'rover',
      line: 27,
      col: 1,
      children: [
        {
          kind: 'assembly',
          name: 'chassis',
          line: 28,
          col: 3,
          children: [{ kind: 'part', primitive: 'box', line: 22, col: 5 }],
        },
        { kind: 'part', primitive: 'sphere', line: 34, col: 3 },
      ],
    }],
  },
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

/** 清单 + 大纲端点（默认 handler 返回空清单，须逐用例注册） */
function useListHandler(items: DesignListItem[] = [DESIGN], outline: Record<string, unknown> = OUTLINE) {
  server.use(
    http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json(items)),
    http.get('/api/v1/workspaces/10/designs/:designId/outline', () => HttpResponse.json(outline)),
  )
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

describe('设计结构页 · 页头与双栏骨架（ADR 0109 C1 / C2）', () => {
  it('页头标题 + 副标题，主体为左产品列表 / 右结构树双栏', async () => {
    useListHandler()
    renderPage()

    expect(await screen.findByRole('heading', { level: 1, name: '设计结构' })).toBeInTheDocument()
    expect(screen.getByText('左侧产品列表、右侧选中产品的结构树')).toBeInTheDocument()
    expect(screen.getByTestId('designs-split')).toBeInTheDocument()
    expect(screen.getByTestId('design-products-box')).toBeInTheDocument()
    expect(screen.getByTestId('design-outline-box')).toBeInTheDocument()
    // 左栏计数在方盒 extra（清单异步到达后再断言）
    await waitFor(() => expect(screen.getByTestId('design-products-box')).toHaveTextContent('共 1 个'))
  })

  it('页面根容器复用质量检查页原语（cn-page / cn-qc-split）', async () => {
    useListHandler()
    const { container } = renderPage()

    expect(await screen.findByTestId('designs-split')).toHaveClass('cn-qc-split')
    expect(container.querySelector('.cn-page.cn-qc-page')).toBeTruthy()
    // 0103 D12 的目录分组小节退役（ADR 0109 D2）：不再渲染 folder 分组容器
    expect(screen.queryByTestId(/design-folder-/)).toBeNull()
  })
})

describe('设计结构页 · 左栏产品列表（ADR 0109 C3 / D2）', () => {
  it('展示设计名称、描述、版本数与更新时间', async () => {
    useListHandler()
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    expect(screen.getByText(/示例结构/)).toBeInTheDocument()
    expect(screen.getByText(/v3/)).toBeInTheDocument()
    expect(screen.getByTestId('design-row-20')).toBeInTheDocument()
  })

  it('空列表展示空态（左右两栏同空态）', async () => {
    useListHandler([])
    renderPage()

    await waitFor(() => expect(screen.getAllByText('还没有结构设计')).toHaveLength(2))
    expect(screen.queryByTestId('design-list')).toBeNull()
  })

  it('目录信息降级为行内 Tag：扁平列表按清单顺序渲染（ADR 0109 D2）', async () => {
    useListHandler([
      { ...DESIGN, id: 20, title: '法兰板', folder: '' },
      { ...DESIGN, id: 21, title: '轮毂', folder: 'parts', kind: 'part' },
      { ...DESIGN, id: 22, title: '底板', folder: 'parts', kind: 'part' },
    ])
    renderPage()

    expect(await screen.findByTestId('design-list')).toBeInTheDocument()
    const rows = within(screen.getByTestId('design-list')).getAllByRole('option')
    expect(rows.map(row => row.getAttribute('data-testid'))).toEqual([
      'design-row-20', 'design-row-21', 'design-row-22',
    ])
    // 目录不再是分组标题，而是行内 Tag
    expect(within(screen.getByTestId('design-row-21')).getAllByText('parts').length).toBeGreaterThan(0)
  })

  it('列表展示类型 / 目录 / 依赖陈旧标记（ADR 0086 C4）', async () => {
    useListHandler([{ ...DESIGN, kind: 'part', folder: 'parts/demo', dependencies_stale: true }])
    renderPage()

    expect(await screen.findByTestId('design-row-20')).toBeInTheDocument()
    expect(screen.getAllByText('零件').length).toBeGreaterThan(0)
    expect(screen.getAllByText('parts/demo').length).toBeGreaterThan(0)
    expect(screen.getByTestId('design-list-stale-20')).toBeInTheDocument()
    expect(screen.getByText('flange-plate')).toBeInTheDocument()
  })

  it('点击行选中、再次点击取消（右栏回到未选中空态）', async () => {
    useListHandler([
      { ...DESIGN, id: 20, title: '法兰板', updated_at: '2026-10-01T08:00:00Z' },
      { ...DESIGN, id: 21, title: '轮毂', kind: 'part', updated_at: '2026-10-05T08:00:00Z' },
    ])
    renderPage()

    const row = await screen.findByTestId('design-row-20')
    fireEvent.click(row)
    await waitFor(() => expect(row).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByTestId('design-outline-box')).toHaveTextContent('结构树：法兰板')

    // 再点取消：右栏回落为「选择左侧产品查看结构树」
    fireEvent.click(row)
    await waitFor(() => expect(row).toHaveAttribute('aria-selected', 'false'))
    expect(screen.getByText('选择左侧产品查看结构树')).toBeInTheDocument()
  })

  it('按类型筛选：零件 / 装配 / 全部（ADR 0103 C8）', async () => {
    useListHandler([
      { ...DESIGN, id: 20, title: '法兰板', kind: 'assembly' },
      { ...DESIGN, id: 21, title: '轮毂', kind: 'part' },
    ])
    renderPage()

    expect(await screen.findByTestId('design-row-21')).toBeInTheDocument()
    expect(screen.getByTestId('design-row-20')).toBeInTheDocument()

    // 筛选控件为 Segmented：点击「零件」只剩零件文件
    const filter = screen.getByTestId('design-kind-filter')
    fireEvent.click(within(filter).getByText('零件'))
    await waitFor(() => expect(screen.queryByTestId('design-row-20')).toBeNull())
    expect(screen.getByTestId('design-row-21')).toBeInTheDocument()

    fireEvent.click(within(filter).getByText('装配'))
    await waitFor(() => expect(screen.queryByTestId('design-row-21')).toBeNull())
    expect(screen.getByTestId('design-row-20')).toBeInTheDocument()

    fireEvent.click(within(filter).getByText('全部'))
    expect(await screen.findByTestId('design-row-21')).toBeInTheDocument()
  })

  it('筛选后左栏为空：右栏回落为未选中空态（边界 #2）', async () => {
    useListHandler([{ ...DESIGN, id: 20, title: '法兰板', kind: 'assembly' }])
    renderPage()

    await screen.findByTestId('design-row-20')
    fireEvent.click(within(screen.getByTestId('design-kind-filter')).getByText('零件'))

    expect(await screen.findByText('该类型下暂无设计')).toBeInTheDocument()
    expect(screen.getByText('选择左侧产品查看结构树')).toBeInTheDocument()
  })

  it('viewer 只读：隐藏新建与编辑 / 删除，保留打开', async () => {
    useListHandler()
    server.use(http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({ ...mockWorkspace, id: 10, current_user_role: 'viewer' })))
    renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建设计/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编\s*辑/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删\s*除/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /打\s*开/ })).toBeInTheDocument()
    // 只读仍可浏览结构树（ADR 0083 D8 / 本 ADR 边界 #4）
    expect(await screen.findByTestId('design-outline-tree')).toBeInTheDocument()
  })

  it('打开设计进入编辑器', async () => {
    useListHandler()
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /打\s*开/ }))
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20')
  })
})

describe('设计结构页 · 右栏装配树（ADR 0109 C4 / D3 / D5 / D6）', () => {
  it('默认选中最近更新的设计并懒加载其大纲', async () => {
    const requested: string[] = []
    server.use(
      http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json([
        { ...DESIGN, id: 20, title: '法兰板', updated_at: '2026-10-01T08:00:00Z' },
        { ...DESIGN, id: 21, title: '轮毂', kind: 'part', updated_at: '2026-10-05T08:00:00Z' },
      ])),
      http.get('/api/v1/workspaces/10/designs/:designId/outline', ({ params }) => {
        requested.push(String(params.designId))
        return HttpResponse.json({ ...OUTLINE, design_id: Number(params.designId) })
      }),
    )
    renderPage()

    // 默认选中最近更新（轮毂），立即拉取它的大纲
    await waitFor(() => expect(requested).toEqual(['21']))
    expect(screen.getByTestId('design-row-21')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('design-outline-box')).toHaveTextContent('结构树：轮毂')
  })

  it('树层级为 系统 → 组件 → 零件，节点带源行元信息', async () => {
    useListHandler()
    renderPage()

    expect(await screen.findByTestId('design-outline-tree')).toBeInTheDocument()
    expect(screen.getByTestId('design-outline-node-design-20-0')).toHaveTextContent('rover')
    expect(screen.getByTestId('design-outline-node-design-20-0')).toHaveTextContent('系统 · 第 27 行')
    expect(screen.getByTestId('design-outline-node-design-20-0-0')).toHaveTextContent('组件 · 第 28 行')
    expect(screen.getByTestId('design-outline-node-design-20-0-0-0')).toHaveTextContent('零件 · 第 22 行')
  })

  it('节点点击打开编辑器并带 ?line= 定位源行（D5）', async () => {
    useListHandler()
    renderPage()

    fireEvent.click(await screen.findByTestId('design-outline-node-design-20-0-1'))
    expect(await screen.findByTestId('editor-stub'))
      .toHaveTextContent('/w/10/design/20?line=34')
  })

  it('选中项被筛选隐藏后回落到可见列表首个（边界 #3）', async () => {
    useListHandler([
      { ...DESIGN, id: 20, title: '法兰板', kind: 'assembly', updated_at: '2026-10-01T08:00:00Z' },
      { ...DESIGN, id: 21, title: '轮毂', kind: 'part', updated_at: '2026-10-05T08:00:00Z' },
    ])
    renderPage()

    // 显式选中装配件，再筛成「零件」→ 选中项不可见，回落列表首个（轮毂）
    fireEvent.click(await screen.findByTestId('design-row-20'))
    await waitFor(() => expect(screen.getByTestId('design-outline-box')).toHaveTextContent('结构树：法兰板'))
    fireEvent.click(within(screen.getByTestId('design-kind-filter')).getByText('零件'))

    await waitFor(() => expect(screen.getByTestId('design-row-21')).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByTestId('design-outline-box')).toHaveTextContent('结构树：轮毂')
  })

  it('空大纲展示占位空态', async () => {
    useListHandler([DESIGN], {
      ...OUTLINE, outline: { children: [] },
    })
    renderPage()

    expect(await screen.findByText('该设计还没有结构节点，点「打开」进入编辑器补充')).toBeInTheDocument()
  })

  it('历史快照派生的大纲标注「历史快照派生」（边界 #6）', async () => {
    useListHandler([DESIGN], { ...OUTLINE, source: 'content' })
    renderPage()

    expect(await screen.findByText('历史快照派生')).toBeInTheDocument()
  })

  it('大纲加载失败给提示并可重试（边界 #5）', async () => {
    let calls = 0
    server.use(
      http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json([DESIGN])),
      http.get('/api/v1/workspaces/10/designs/:designId/outline', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ detail: '编译失败' }, { status: 400 })
          : HttpResponse.json(OUTLINE)
      }),
    )
    renderPage()

    expect(await screen.findByTestId('design-outline-error')).toHaveTextContent('结构加载失败')
    fireEvent.click(within(screen.getByTestId('design-outline-error')).getByRole('button', { name: /重\s*试/ }))
    expect(await screen.findByTestId('design-outline-tree')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

})

describe('设计结构页 · 新建 / 改名 / 删除（能力不减，ADR 0109 C5）', () => {
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

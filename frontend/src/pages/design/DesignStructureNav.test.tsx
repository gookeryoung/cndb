/** DesignStructureNav 测试 —— 设计侧栏「产品列表 ↔ 结构树」两态（ADR 0109 D2 / D4 / D5）
 *
 * 覆盖：列表态（搜索 / 类型筛选 / 新建 / 改名 / 删除 / viewer 门控）、
 * 选产品就地切树态且 URL 变化、返回列表不改 URL、
 * 结构树（根 = 产品 / 懒加载大纲 / 层级 / ?line= 定位 / 缓存优先 / 历史快照 / 依赖陈旧 / use 源文件）。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import DesignStructureNav from './DesignStructureNav'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type { DesignDetail, DesignListItem, DesignOutlineNode } from '@/api'

const AUTH = { initialAuth: { user: null, token: 'fake' } }

const DESIGN: DesignListItem = {
  id: 20,
  workspace_id: 10,
  title: '小车',
  description: '',
  kind: 'assembly',
  file_key: 'rover',
  folder: '',
  dependencies_stale: false,
  version_count: 2,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-02T08:00:00Z',
}

/** 系统级大纲：system rover → 组件 chassis（差集 → 立方体 + 圆柱）+ 顶层零件球体 */
const OUTLINE: DesignOutlineNode[] = [{
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
      children: [{
        kind: 'group',
        op: 'difference',
        line: 21,
        col: 3,
        children: [
          { kind: 'part', primitive: 'box', line: 22, col: 5 },
          { kind: 'part', primitive: 'cyl', line: 23, col: 27 },
        ],
      }],
    },
    { kind: 'part', primitive: 'sphere', line: 34, col: 3 },
  ],
}]

function EditorStub() {
  const loc = useLocation()
  return <div data-testid="editor-stub">{loc.pathname}{loc.search}</div>
}

function renderNav(route: string) {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/design" element={<DesignStructureNav workspaceId="10" />} />
      <Route
        path="/w/:wid/design/:designId"
        element={<><DesignStructureNav workspaceId="10" /><EditorStub /></>}
      />
    </Routes>,
    { route, ...AUTH },
  )
}

function useListHandler(items: DesignListItem[] = [DESIGN]) {
  server.use(http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json(items)))
}

function useOutlineHandler(source: 'compiled' | 'content' = 'compiled') {
  server.use(http.get('/api/v1/workspaces/10/designs/:designId/outline', ({ params }) => {
    const designId = Number(params.designId)
    return HttpResponse.json({
      design_id: designId,
      version_number: 2,
      outline: { children: designId === 20 ? OUTLINE : [] },
      source,
    })
  }))
}

function useViewerHandler() {
  server.use(http.get('/api/v1/workspaces/10', () => HttpResponse.json({
    ...mockWorkspace, id: 10, current_user_role: 'viewer',
  })))
}

/** 点击树节点展开箭头（antd 展开动画窗口约 600ms 会吞下一次点击，先等待） */
async function expandNode(testId: string) {
  await new Promise(resolve => setTimeout(resolve, 600))
  const switcher = screen.getByTestId(testId)
    .closest('.ant-tree-treenode')
    ?.querySelector('.ant-tree-switcher')
  expect(switcher).toBeTruthy()
  fireEvent.click(switcher as Element)
  await waitFor(() => {
    expect(screen.getByTestId(testId).closest('.ant-tree-treenode')?.getAttribute('aria-expanded')).toBe('true')
  })
}

async function openRowMenu(title: string) {
  fireEvent.click(await screen.findByLabelText(`${title} 操作`))
  return screen.findAllByRole('menuitem')
}

describe('设计侧栏 · 产品列表态（ADR 0109 D2 / C4）', () => {
  it('根页渲染产品列表：名称 / 类型 / 版本 / 更新时间，不渲染结构树', async () => {
    useListHandler()
    renderNav('/w/10/design')

    expect(await screen.findByTestId('design-products-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('design-outline-panel')).toBeNull()
    expect(await screen.findByTestId('design-row-20')).toHaveTextContent('小车')
    expect(screen.getByTestId('design-row-20')).toHaveTextContent('装配')
    expect(screen.getByTestId('design-row-20')).toHaveTextContent('v2')
    expect(screen.getByTestId('design-row-20')).toHaveTextContent('2026')
    expect(screen.getByTestId('design-nav-filter')).toBeInTheDocument()
    expect(screen.getByTestId('design-kind-filter')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新建设计/ })).toBeInTheDocument()
  })

  it('标题搜索与类型筛选只收窄列表，不影响 Content', async () => {
    useListHandler([
      DESIGN,
      { ...DESIGN, id: 21, title: '法兰板', kind: 'part' },
    ])
    renderNav('/w/10/design')

    fireEvent.change(await screen.findByTestId('design-nav-filter'), { target: { value: '小车' } })
    await waitFor(() => expect(screen.queryByTestId('design-row-21')).toBeNull())
    expect(screen.getByTestId('design-row-20')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('design-nav-filter'), { target: { value: '' } })
    fireEvent.click(within(screen.getByTestId('design-kind-filter')).getByText('零件'))
    await waitFor(() => expect(screen.queryByTestId('design-row-20')).toBeNull())
    expect(screen.getByTestId('design-row-21')).toBeInTheDocument()
  })

  it('空列表显示新建引导，viewer 不显示新建入口', async () => {
    useListHandler([])
    useViewerHandler()
    renderNav('/w/10/design')

    expect(await screen.findByText('当前工作区还没有结构设计')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建设计/ })).toBeNull()
  })

  it('viewer 行内菜单只有打开，没有编辑 / 删除', async () => {
    useListHandler()
    useViewerHandler()
    renderNav('/w/10/design')

    await screen.findByTestId('design-row-20')
    fireEvent.click(screen.getByLabelText('小车 操作'))
    expect(await screen.findByRole('menuitem', { name: /打开/ })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /编辑/ })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: /删除/ })).toBeNull()
  })
})

describe('设计侧栏 · 就地切入结构树（ADR 0109 C1 / C2 / D4）', () => {
  it('点击产品：URL 进入编辑器，侧栏就地切树态（列表消失）', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design')

    fireEvent.click(await screen.findByTestId('design-row-20'))

    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20')
    expect(await screen.findByTestId('design-outline-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('design-products-panel')).toBeNull()
  })

  it('「产品列表」返回键只切侧栏态，URL 与 Content 不变', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20')

    await screen.findByTestId('design-outline-panel')
    fireEvent.click(screen.getByTestId('design-nav-back'))

    expect(await screen.findByTestId('design-products-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('design-outline-panel')).toBeNull()
    expect(screen.getByTestId('editor-stub')).toHaveTextContent('/w/10/design/20')
  })

  it('进入编辑器页直接呈现当前产品结构树', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20')

    expect(await screen.findByText('rover')).toBeInTheDocument()
    expect(screen.getByTestId('design-node-20')).toHaveTextContent('小车')
    expect(screen.getByTestId('design-node-20').closest('.ant-tree-treenode')?.className)
      .toContain('ant-tree-treenode-selected')
  })
})

describe('设计侧栏 · 结构树（ADR 0109 D5 / D6）', () => {
  it('系统 → 组件 → 分组 → 零件逐级展开', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20')

    expect(await screen.findByText('rover')).toBeInTheDocument()
    expect(screen.getByText('系统 · 第 27 行 · 3 个零件')).toBeInTheDocument()

    await expandNode('design-outline-node-design-20-0')
    expect(await screen.findByText('chassis')).toBeInTheDocument()
    expect(screen.getByText('组件 · 第 28 行 · 2 个零件')).toBeInTheDocument()

    await expandNode('design-outline-node-design-20-0-0')
    expect(await screen.findByText('差集')).toBeInTheDocument()
    expect(screen.getByText('球体')).toBeInTheDocument()
  })

  it('?line= 反选大纲节点并展开祖先链', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20?line=34')

    expect(await screen.findByText('rover')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('球体').closest('.ant-tree-treenode')?.className)
        .toContain('ant-tree-treenode-selected')
    })
    expect(screen.getByText('chassis')).toBeInTheDocument()
  })

  it('?line= 早于首行时回落到产品根选中', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20?line=1')

    expect(await screen.findByText('rover')).toBeInTheDocument()
    expect(screen.getByTestId('design-node-20').closest('.ant-tree-treenode')?.className)
      .toContain('ant-tree-treenode-selected')
  })

  it('点击零件节点进入编辑器并定位源行', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20')

    await screen.findByText('rover')
    await expandNode('design-outline-node-design-20-0')
    fireEvent.click(await screen.findByText('球体'))
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20?line=34')
  })

  it('历史快照派生与依赖陈旧标记', async () => {
    useListHandler([{ ...DESIGN, kind: 'part', dependencies_stale: true }])
    useOutlineHandler('content')
    renderNav('/w/10/design/20')

    expect(await screen.findByTestId('design-stale-20')).toBeInTheDocument()
    expect(await screen.findByText('历史快照派生')).toBeInTheDocument()
    expect(screen.getByText('零件')).toBeInTheDocument()
  })

  it('use 实例带源文件时点击打开源文件（ADR 0086 C7）', async () => {
    useListHandler()
    server.use(http.get('/api/v1/workspaces/10/designs/:designId/outline', ({ params }) => {
      const designId = Number(params.designId)
      return HttpResponse.json({
        design_id: designId,
        version_number: 2,
        outline: {
          children: designId === 20
            ? [{
                kind: 'assembly',
                name: 'chassis',
                line: 28,
                col: 3,
                ref: { file_id: 30, file_key: 'rover__chassis', kind: 'part' },
                children: [{ kind: 'part', primitive: 'box', line: 5, col: 3 }],
              }]
            : [],
        },
        source: 'compiled',
      })
    }))
    renderNav('/w/10/design/20')

    const label = await screen.findByText('组件（rover__chassis） · 1 个零件')
    fireEvent.click(label)
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/30')
  })

  it('IR 快照缓存命中时不重复请求 /outline（ADR 0086 D10）', async () => {
    useListHandler()
    let outlineCalls = 0
    server.use(http.get('/api/v1/workspaces/10/designs/:designId/outline', () => {
      outlineCalls += 1
      return HttpResponse.json({ detail: 'should not be called' }, { status: 500 })
    }))
    const { queryClient } = renderNav('/w/10/design')
    await screen.findByTestId('design-row-20')

    // 列表态先播种编辑器 IR 缓存，再选产品：树态复用快照，不打 outline 端点
    queryClient.setQueryData(['designs', '10', '20', 'ir'], {
      design_id: 20,
      version_number: 2,
      content_hash: 'h',
      ir: { version: 4, units: { length: 'mm', angle: 'deg' }, params: [], nodes: [], outline: { children: OUTLINE } },
    })
    fireEvent.click(screen.getByTestId('design-row-20'))

    expect(await screen.findByText('rover')).toBeInTheDocument()
    expect(outlineCalls).toBe(0)
  })
})

describe('设计侧栏 · 新建 / 改名 / 删除（ADR 0109 D2）', () => {
  it('新建设计后进入编辑器', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/designs', () => HttpResponse.json([])),
      http.post('/api/v1/workspaces/10/designs', async ({ request }) => {
        const body = await request.json() as { title: string }
        return HttpResponse.json({
          ...DESIGN, id: 31, title: body.title, version_number: 1, content: '', content_hash: 'h',
        } satisfies DesignDetail)
      }),
      http.get('/api/v1/workspaces/10/designs/:designId/outline', () => HttpResponse.json({
        design_id: 31, version_number: 1, outline: { children: [] }, source: 'compiled',
      })),
    )
    renderNav('/w/10/design')

    fireEvent.click(await screen.findByRole('button', { name: /新建设计/ }))
    fireEvent.change(await screen.findByLabelText('名称'), { target: { value: '新法兰板' } })
    fireEvent.click(await screen.findByRole('button', { name: /创\s*建/ }))

    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/31')
  })

  it('改名走更新接口并刷新列表', async () => {
    useListHandler()
    let renamed = ''
    server.use(http.put('/api/v1/workspaces/10/designs/20', async ({ request }) => {
      const body = await request.json() as { title: string }
      renamed = body.title
      return HttpResponse.json({ ...DESIGN, title: body.title })
    }))
    renderNav('/w/10/design')

    await openRowMenu('小车')
    fireEvent.click(await screen.findByRole('menuitem', { name: /编辑/ }))
    const input = await screen.findByLabelText('名称')
    fireEvent.change(input, { target: { value: '新小车' } })
    fireEvent.click(await screen.findByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(renamed).toBe('新小车'))
  })

  it('删除需二次确认并调用删除接口', async () => {
    useListHandler([
      DESIGN,
      { ...DESIGN, id: 21, title: '法兰板' },
    ])
    let removed = 0
    server.use(http.delete('/api/v1/workspaces/10/designs/20', () => {
      removed += 1
      return new HttpResponse(null, { status: 204 })
    }))
    renderNav('/w/10/design')

    await openRowMenu('小车')
    fireEvent.click(await screen.findByRole('menuitem', { name: /删除/ }))
    fireEvent.click(await screen.findByRole('button', { name: /删\s*除/ }))

    await waitFor(() => expect(removed).toBe(1))
  })
})

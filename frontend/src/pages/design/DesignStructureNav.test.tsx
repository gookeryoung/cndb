/** DesignStructureNav 测试 —— 设计侧栏装配结构树（ADR 0084 C1/C2）
 *
 * 覆盖：设计清单 + 标题过滤 / 展开懒加载大纲 / 系统 → 组件 → 分组 → 零件层级 /
 * 节点点击定位（?line=）/ 编辑器页自动展开并高亮当前设计 / 历史快照派生标记. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import DesignStructureNav from './DesignStructureNav'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { DesignListItem, DesignOutlineNode } from '@/api'

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
  // 通配 designId：过滤用例会同时拉多个设计；非 20 返回空大纲
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

describe('DesignStructureNav 侧栏装配结构（0084）', () => {
  it('管理页：列出设计，展开后懒加载并展示系统 / 组件 / 分组 / 零件', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design')

    expect(await screen.findByTestId('design-node-20')).toHaveTextContent('小车')
    await expandNode('design-node-20')
    expect(await screen.findByText('rover')).toBeInTheDocument()
    expect(screen.getByText('系统 · 第 27 行 · 3 个零件')).toBeInTheDocument()

    await expandNode('design-outline-node-design-20-0')
    expect(await screen.findByText('chassis')).toBeInTheDocument()
    expect(screen.getByText('组件 · 第 28 行 · 2 个零件')).toBeInTheDocument()

    await expandNode('design-outline-node-design-20-0-0')
    expect(await screen.findByText('差集')).toBeInTheDocument()
    expect(screen.getByText('球体')).toBeInTheDocument()
  })

  it('编辑器页自动展开当前设计并高亮（进入模块即见装配结构）', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20')

    expect(await screen.findByText('rover')).toBeInTheDocument()
    const node = screen.getByTestId('design-node-20').closest('.ant-tree-treenode')
    expect(node?.className).toContain('ant-tree-treenode-selected')
    // 自动展开即触发大纲加载（无需手动点箭头）
    expect(screen.getByText('系统 · 第 27 行 · 3 个零件')).toBeInTheDocument()
  })

  it('点击零件节点进入编辑器并定位源行（?line=）', async () => {
    useListHandler()
    useOutlineHandler()
    renderNav('/w/10/design/20')

    await screen.findByText('rover')
    await expandNode('design-outline-node-design-20-0')
    fireEvent.click(await screen.findByText('球体'))
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20?line=34')
  })

  it('点击设计根进入编辑器', async () => {
    useListHandler()
    renderNav('/w/10/design')

    fireEvent.click(await screen.findByTestId('design-node-20'))
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/20')
  })

  it('标题过滤：只保留命中设计并自动展开', async () => {
    useListHandler([DESIGN, { ...DESIGN, id: 21, title: '法兰板' }])
    useOutlineHandler()
    renderNav('/w/10/design')

    fireEvent.change(screen.getByTestId('design-nav-filter'), { target: { value: '小车' } })
    expect(await screen.findByTestId('design-node-20')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('design-node-21')).toBeNull())
    // 过滤命中自动展开并加载大纲
    await waitFor(() => {
      expect(screen.getByTestId('design-node-20').closest('.ant-tree-treenode')?.getAttribute('aria-expanded'))
        .toBe('true')
    })
    expect(await screen.findByText('rover')).toBeInTheDocument()
  })

  it('历史快照派生（source=content）在设计节点标注', async () => {
    useListHandler()
    useOutlineHandler('content')
    renderNav('/w/10/design')

    expect(await screen.findByTestId('design-node-20')).toBeInTheDocument()
    await expandNode('design-node-20')
    expect(await screen.findByText('历史快照派生')).toBeInTheDocument()
  })

  it('零件文件显示「零件」标签，依赖陈旧显示标记（ADR 0086 C4）', async () => {
    useListHandler([{ ...DESIGN, kind: 'part', dependencies_stale: true }])
    renderNav('/w/10/design')

    expect(await screen.findByText('零件')).toBeInTheDocument()
    expect(screen.getByTestId('design-stale-20')).toBeInTheDocument()
  })

  it('use 实例带源文件时点击打开源文件（ADR 0086 C7）', async () => {
    useListHandler()
    // 组件 chassis 来自外部零件文件 file_id=30（IR v4 ref）
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

    expect(await screen.findByText('组件（rover__chassis） · 1 个零件')).toBeInTheDocument()
    fireEvent.click(screen.getByText('组件（rover__chassis） · 1 个零件'))
    expect(await screen.findByTestId('editor-stub')).toHaveTextContent('/w/10/design/30')
  })
})

/** DesignEditorPage 测试 —— 编辑器主流程 + 布局（ADR 0079 §7 / ADR 0103 §7）.
 *
 * jsdom 无 WebGL：PreviewCanvas 与 DesignMoreMenu 必须 mock（lazy chunk 的
 * 真实渲染与导出由 exporters 单测 + e2e 覆盖）；
 * 编辑器内容变更经 EditorView.findFromDOM 驱动真实 CodeMirror transaction，
 * 覆盖：源码展示 / 诊断回显 / 保存（Ctrl+S）/ 保存失败保留草稿 / 参数常驻面板 /
 * 视口工具条与状态条 / 分栏预设持久化 / 参数面板折叠 / 树↔视口高亮 /
 * viewer 只读 / 版本回看与恢复（「更多」菜单入口）.
 */

import { describe, expect, it, vi } from 'vitest'
import { useEffect } from 'react'
import { http, HttpResponse } from 'msw'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { EditorView } from '@codemirror/view'
import { startCompletion } from '@codemirror/autocomplete'
import { Routes, Route } from 'react-router-dom'
import DesignEditorPage, { PARAMS_COLLAPSED_KEY, SPLIT_KEY } from './DesignEditorPage'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type {
  DesignDetail, DesignIR, DesignPreviewResult, DesignVersionDetail, DesignVersionItem,
} from '@/api'

/** PreviewCanvas stub：上报统计 / 暴露视口 API / 记录高亮与网格调用 */
const viewport = vi.hoisted(() => ({
  highlight: vi.fn(),
  orientTo: vi.fn(),
  fit: vi.fn(),
  setGridVisible: vi.fn(),
  stats: [] as Array<{ nodes: number; triangles: number }>,
}))

vi.mock('./PreviewCanvas', () => ({
  default: function PreviewCanvasStub({
    ir, onStats, onViewportApi,
  }: {
    ir: DesignIR | null
    onStats?: (stats: { nodes: number; triangles: number }) => void
    onViewportApi?: (api: typeof viewport | null) => void
  }) {
    // 等价真实组件挂载：上报统计与暴露视口 API（在 effect 中，避免渲染期改父状态）
    useEffect(() => {
      onStats?.({ nodes: ir?.nodes.length ?? 0, triangles: 42 })
    }, [ir, onStats])
    useEffect(() => {
      onViewportApi?.({
        highlight: viewport.highlight,
        orientTo: viewport.orientTo,
        fit: viewport.fit,
        setGridVisible: viewport.setGridVisible,
        stats: [],
      })
      return () => onViewportApi?.(null)
    }, [onViewportApi])
    return <div data-testid="preview-canvas-stub">{ir ? `节点数:${ir.nodes.length}` : '空'}</div>
  },
}))

const moreMenu = vi.hoisted(() => vi.fn())
vi.mock('./DesignMoreMenu', () => ({
  default: function DesignMoreMenuStub({ ir, title, onHistory }: {
    ir: DesignIR | null
    title: string
    versionCount: number
    onHistory: () => void
  }) {
    moreMenu({ ir, title })
    return (
      <button type="button" data-testid="more-menu-stub" onClick={onHistory}>
        更多:{title}
      </button>
    )
  },
}))

const AUTH = { initialAuth: { user: null, token: 'fake' } }

const CONTENT = [
  'param width = 80',
  'box(size = [width, 40, 12])',
].join('\n')

const IR: DesignIR = {
  version: 5,
  units: { length: 'mm', angle: 'deg' },
  params: [{ name: 'width', value: 80 }],
  nodes: [{ op: 'box', size: [80, 40, 12] }],
  outline: {
    children: [{ kind: 'part', primitive: 'box', line: 2, col: 1, node_index: 0 }],
  },
}

const DETAIL: DesignDetail = {
  id: 20,
  workspace_id: 10,
  title: '法兰板',
  description: '示例结构',
  kind: 'assembly',
  file_key: 'flange-plate',
  folder: '',
  dependencies_stale: false,
  version_count: 2,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-02T08:00:00Z',
  content: CONTENT,
  content_hash: 'abc123',
  version_number: 2,
}

const VERSIONS: DesignVersionItem[] = [
  { id: 202, design_id: 20, version_number: 2, change_type: 'manual', comment: '调宽度', created_by_id: 1, created_at: '2026-10-02T08:00:00Z' },
  { id: 201, design_id: 20, version_number: 1, change_type: 'manual', comment: '', created_by_id: 1, created_at: '2026-10-01T08:00:00Z' },
]

const V1_CONTENT = 'param width = 60\nbox(size = [width, 40, 12])'

const V1_DETAIL: DesignVersionDetail = {
  ...VERSIONS[1]!,
  content: V1_CONTENT,
  compiled: { ...IR, params: [{ name: 'width', value: 60 }], nodes: [{ op: 'box', size: [60, 40, 12] }] },
  dependencies: [],
}

/** preview 请求体记录 */
const previewBodies: Array<{ content: string; overrides?: Record<string, number> | null; design_id?: number | null }> = []

function useDefaultHandlers(preview: () => DesignPreviewResult = () => ({ ok: true, ir: IR, diagnostics: [] })) {
  previewBodies.length = 0
  viewport.highlight.mockClear()
  viewport.setGridVisible.mockClear()
  server.use(
    http.get('/api/v1/workspaces/10/designs/20', () => HttpResponse.json(DETAIL)),
    http.get('/api/v1/workspaces/10/designs/20/ir', () =>
      HttpResponse.json({ design_id: 20, version_number: 2, content_hash: 'abc123', ir: IR })),
    http.get('/api/v1/workspaces/10/designs/20/versions', () => HttpResponse.json(VERSIONS)),
    http.get('/api/v1/workspaces/10/designs/20/diff', () => HttpResponse.json({
      base_version: 1,
      head_version: 2,
      diff: '',
      added: 0,
      removed: 0,
      summary: {
        available: true,
        params: { added: [], removed: [], changed: [] },
        nodes: { base: 1, head: 1 },
        assemblies: { added: [], removed: [] },
      },
    })),
    http.post('/api/v1/workspaces/10/designs/preview', async ({ request }) => {
      const body = await request.json() as { content: string; overrides?: Record<string, number> | null }
      previewBodies.push(body)
      return HttpResponse.json(preview())
    }),
  )
}

function renderPage(route = '/w/10/design/20') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/design/:designId" element={<DesignEditorPage />} />
    </Routes>,
    { route, ...AUTH },
  )
}

/** 经真实 CodeMirror transaction 修改编辑器内容（触发 onChange → dirty）
 *
 * dispatch 不走 RTL 的事件通道，必须包 act：否则 onChange 引发的状态更新与
 * 「Ctrl+S 监听重绑」的 effect 可能在断言之后才落地，慢机（CI 4 vCPU 跑 3 分片）
 * 上会退化成「按了 Ctrl+S 但没触发保存」的伪失败。
 */
function editViaCodeMirror(container: HTMLElement, insert: string) {
  const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)
  if (!view) throw new Error('编辑器视图未挂载')
  act(() => {
    view.dispatch({ changes: { from: view.state.doc.length, insert } })
  })
}

/** 编辑器全文（CodeMirror 行内含多个高亮 span，须按整体 textContent 断言） */
function cmText(container: HTMLElement): string {
  return container.querySelector('.cm-content')?.textContent ?? ''
}

/** 等编辑器就绪：编辑器已挂载且 placeholder（仅空文档渲染）消失，即详情 value 已同步 */
async function waitForEditorReady(container: HTMLElement) {
  await waitFor(() => {
    expect(container.querySelector('.cm-editor')).not.toBeNull()
    expect(container.querySelector('.cm-placeholder')).toBeNull()
  })
}

describe('DesignEditorPage 编辑器主流程', () => {
  it('展示标题、版本号、源码与预览 IR', async () => {
    useDefaultHandlers()
    const { container } = renderPage()

    expect(await screen.findByText('法兰板')).toBeInTheDocument()
    expect(screen.getAllByText('v2').length).toBeGreaterThan(0)
    // placeholder 与初始内容同文案，就绪判定以 placeholder 消失为准
    await waitForEditorReady(container)
    expect(cmText(container)).toContain('box(size = [width, 40, 12])')
    // 预览走防抖 → 编译通过 → stub 收到 IR（节点数 1）
    expect(await screen.findByText('节点数:1')).toBeInTheDocument()
    // 版本历史入口收进「更多」菜单（ADR 0103 D6）
    expect(screen.getByTestId('more-menu-stub')).toHaveTextContent('更多:法兰板')
  })

  it('use 字符串位经注入的 designsApi.list 返回零件名候选（0110 C10）', async () => {
    useDefaultHandlers()
    let listCalls = 0
    server.use(
      http.get('/api/v1/workspaces/10/designs', () => {
        listCalls += 1
        return HttpResponse.json([
          {
            id: 21, workspace_id: 10, title: '车轮', description: '', kind: 'part',
            file_key: 'wheel', folder: '', dependencies_stale: false, version_count: 1,
            created_at: null, updated_at: null,
          },
        ])
      }),
    )
    const { container } = renderPage()
    await waitForEditorReady(container)

    const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)!
    const insert = '\nuse "'
    act(() => {
      view.dispatch({
        changes: { from: view.state.doc.length, insert },
        selection: { anchor: view.state.doc.length + insert.length },
      })
      startCompletion(view)
    })

    // 候选来自 mock 列表；再次唤起命中会话内缓存，不重复请求
    expect(await screen.findByText('wheel')).toBeInTheDocument()
    act(() => { startCompletion(view) })
    await waitFor(() => expect(listCalls).toBe(1))
  })

  it('?line= 定位源行并选中整行（0083 D7）', async () => {
    useDefaultHandlers()
    const { container } = renderPage('/w/10/design/20?line=2')

    await waitForEditorReady(container)
    const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)
    expect(view).not.toBeNull()
    // 第 2 行 = "box(size = [width, 40, 12])"，起点为第 1 行长度 + 换行
    await waitFor(() => expect(view!.state.selection.main.from).toBe(CONTENT.indexOf('\n') + 1))
    expect(view!.state.sliceDoc(view!.state.selection.main.from, view!.state.selection.main.to))
      .toBe('box(size = [width, 40, 12])')
  })

  it('?line= 越界时钳制到末行（0083 D7）', async () => {
    useDefaultHandlers()
    const { container } = renderPage('/w/10/design/20?line=99')

    await waitForEditorReady(container)
    const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)
    await waitFor(() => expect(view!.state.selection.main.from).toBe(CONTENT.indexOf('\n') + 1))
  })

  it('?line= 触发树↔视口高亮（ADR 0103 C7 / D9）', async () => {
    useDefaultHandlers()
    renderPage('/w/10/design/20?line=2')

    await waitFor(() => expect(viewport.highlight).toHaveBeenCalledWith([0]))
  })

  it('IR 无 node_index（v4 旧快照）时高亮静默降级（I2）', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/ir', () =>
      HttpResponse.json({
        design_id: 20,
        version_number: 2,
        content_hash: 'abc',
        ir: {
          version: 4,
          units: { length: 'mm', angle: 'deg' },
          params: [],
          nodes: [{ op: 'box', size: [1, 1, 1] }],
          outline: { children: [{ kind: 'part', primitive: 'box', line: 1, col: 1 }] },
        },
      })))
    renderPage('/w/10/design/20?line=1')

    expect(await screen.findByTestId('preview-canvas-stub')).toBeInTheDocument()
    expect(viewport.highlight).not.toHaveBeenCalled()
  })

  it('preview 返回诊断时回显错误行与消息', async () => {
    useDefaultHandlers(() => ({
      ok: false,
      ir: null,
      diagnostics: [{ severity: 'error', line: 2, col: 1, message: '未知图元 foo' }],
    }))
    const { container } = renderPage()

    // 干净打开不发 preview（I6）：先编辑触发防抖 preview，再等诊断回显
    await waitForEditorReady(container)
    editViaCodeMirror(container, '\nfoo()')
    expect(await screen.findByText('第2行')).toBeInTheDocument()
    expect(screen.getByText('未知图元 foo')).toBeInTheDocument()
    // 错误行底色装饰
    await waitFor(() => expect(container.querySelector('.cn-dsl-diag-error')).not.toBeNull())
  })

  it('编辑产生 dirty，Ctrl+S 保存成功并提示新版本号', async () => {
    useDefaultHandlers()
    let saved: { content: string } | undefined
    server.use(http.put('/api/v1/workspaces/10/designs/20/content', async ({ request }) => {
      const body = await request.json() as { content: string; comment?: string }
      saved = { content: body.content }
      return HttpResponse.json({ ...DETAIL, content: body.content, version_number: 3, version_count: 3 })
    }))
    const { container } = renderPage()

    await waitForEditorReady(container)
    editViaCodeMirror(container, '\n// 加工备注')
    expect(await screen.findByText('未保存')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 's', ctrlKey: true })
    // 保存要等一次 msw 往返；CI 高负载下默认 1s 的 waitFor 窗口偏紧
    await waitFor(() => expect(saved).toBeDefined(), { timeout: 3000 })
    expect(saved!.content).toBe(`${CONTENT}\n// 加工备注`)
    expect(await screen.findByText(/已保存为第 3 版/)).toBeInTheDocument()
  })

  it('保存失败显示「草稿已保留」且草稿不丢', async () => {
    useDefaultHandlers()
    server.use(http.put('/api/v1/workspaces/10/designs/20/content', () =>
      HttpResponse.json({ detail: '第2行第1列：未知图元 foo', code: 'design_compile_failed' }, { status: 400 })))
    const { container } = renderPage()

    await waitForEditorReady(container)
    editViaCodeMirror(container, '\n// 待修复草稿')
    // 保存按钮在预览编译中禁用（canSave 含 !preview.compiling），先等它可用
    const saveButton = await screen.findByRole('button', { name: name => name.includes('保存') })
    await waitFor(() => expect(saveButton).not.toBeDisabled())
    fireEvent.click(saveButton)

    expect(await screen.findByText('保存被拒绝（草稿已保留）')).toBeInTheDocument()
    expect(await screen.findByText(/第2行第1列：未知图元 foo/)).toBeInTheDocument()
    // 草稿仍在编辑器且仍标记未保存
    expect(cmText(container)).toContain('// 待修复草稿')
    expect(screen.getByText('未保存')).toBeInTheDocument()
  })

  it('干净打开直接消费 IR 快照，不发 preview（ADR 0086 I6）', async () => {
    useDefaultHandlers()
    renderPage()

    // 详情与 IR 到达后即渲染（stub 收到快照 IR），且 preview 零请求
    expect(await screen.findByText('节点数:1')).toBeInTheDocument()
    await new Promise(resolve => setTimeout(resolve, 450))
    expect(previewBodies.length).toBe(0)
    expect(screen.getByTestId('design-compile-ok')).toBeInTheDocument()
  })

  it('参数面板常驻：直接渲染 IR 参数，改参后 overrides 进入 preview 请求（C5）', async () => {
    useDefaultHandlers()
    renderPage()

    // 不再需要点按钮打开抽屉（面板常驻，ADR 0103 D2）
    const input = await screen.findByLabelText('参数 width')
    expect((input as HTMLInputElement).value).toBe('80')

    fireEvent.change(input, { target: { value: '100' } })
    await waitFor(() => expect(previewBodies.length).toBeGreaterThan(0))
    expect(previewBodies[previewBodies.length - 1]!.overrides).toEqual({ width: 100 })
    expect(previewBodies[previewBodies.length - 1]!.design_id).toBe(20)
    expect(await screen.findByRole('button', { name: /重置/ })).toBeInTheDocument()
  })

  it('参数面板折叠态持久化到 localStorage（C5 / I5）', async () => {
    useDefaultHandlers()
    renderPage()

    fireEvent.click(await screen.findByTestId('design-params-collapse'))
    expect(window.localStorage.getItem(PARAMS_COLLAPSED_KEY)).toBe('1')
    expect(await screen.findByTestId('design-params-expand')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('design-params-expand'))
    expect(window.localStorage.getItem(PARAMS_COLLAPSED_KEY)).toBe('0')
  })

  it('视口状态条显示单位与统计（C4 / D5）', async () => {
    useDefaultHandlers()
    renderPage()

    // 单位取 IR units.length（不硬编码），三角数来自 onStats；IR 异步到达，等一次
    expect(await screen.findByText('mm · 节点 1 · 三角 42')).toBeInTheDocument()
  })

  it('视口工具条：七向定向 / 布满视图 / 网格开关（C3）', async () => {
    useDefaultHandlers()
    renderPage()

    expect(await screen.findByTestId('design-viewport-toolbar')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '视图定向' }))
    fireEvent.click(await screen.findByText('俯视'))
    expect(viewport.orientTo).toHaveBeenCalledWith('top')

    fireEvent.click(screen.getByRole('button', { name: '布满视图' }))
    expect(viewport.fit).toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('design-grid-toggle'))
    expect(viewport.setGridVisible).toHaveBeenLastCalledWith(false)
    // antd Button 变更 props 后重挂 DOM 节点：重新查询再断言属性
    expect(screen.getByTestId('design-grid-toggle')).toHaveAttribute('aria-pressed', 'false')
  })

  it('分栏三档预设切换并持久化（C2 / D10）', async () => {
    useDefaultHandlers()
    renderPage()

    const preset = await screen.findByTestId('design-split-preset')
    expect(preset).toBeInTheDocument()
    expect(await screen.findByTestId('design-splitter')).toBeInTheDocument()

    fireEvent.click(screen.getByText('编辑'))
    await waitFor(() => expect(window.localStorage.getItem(SPLIT_KEY)).toBe('60'))
    fireEvent.click(screen.getByText('视口'))
    await waitFor(() => expect(window.localStorage.getItem(SPLIT_KEY)).toBe('40'))
    fireEvent.click(screen.getByText('均分'))
    await waitFor(() => expect(window.localStorage.getItem(SPLIT_KEY)).toBe('50'))
  })

  it('分栏比例从 localStorage 恢复（C2 / I5）', async () => {
    window.localStorage.setItem(SPLIT_KEY, '70')
    useDefaultHandlers()
    renderPage()

    const workbench = await screen.findByTestId('design-workbench')
    await waitFor(() => expect(workbench.getAttribute('style')).toContain('70fr'))
  })

  it('窄屏（<1024px）不渲染 splitter、不套用比例（C2 降级路径）', async () => {
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: query.includes('1023.98px'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia
    try {
      window.localStorage.setItem(SPLIT_KEY, '70')
      useDefaultHandlers()
      renderPage()

      const workbench = await screen.findByTestId('design-workbench')
      expect(screen.queryByTestId('design-splitter')).toBeNull()
      expect(workbench.getAttribute('style')).toBeNull()
      // 视口工具条 / 状态条 / 参数面板在窄屏同样可达（I4）
      expect(screen.getByTestId('design-viewport-toolbar')).toBeInTheDocument()
      expect(screen.getByTestId('design-statusbar')).toBeInTheDocument()
      expect(screen.getByTestId('design-params-panel')).toBeInTheDocument()
    } finally {
      window.matchMedia = original
    }
  })

  it('依赖陈旧显示横幅，刷新落新版本（ADR 0086 D6）', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20', () =>
      HttpResponse.json({ ...DETAIL, dependencies_stale: true })))
    let refreshed = false
    server.use(http.post('/api/v1/workspaces/10/designs/20/refresh', () => {
      refreshed = true
      return HttpResponse.json({ ...DETAIL, dependencies_stale: false, version_number: 3 })
    }))
    renderPage()

    expect(await screen.findByTestId('design-stale-banner')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '刷新依赖' }))
    await waitFor(() => expect(refreshed).toBe(true))
    expect(await screen.findByText(/依赖已刷新，保存为第 3 版/)).toBeInTheDocument()
  })

  it('viewer 只读态：标记只读且保存禁用', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({ ...mockWorkspace, id: 10, current_user_role: 'viewer' })))
    renderPage()

    expect(await screen.findByText('只读')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /保\s*存/ })).toBeDisabled()
  })

  it('版本回看：从「更多」菜单打开抽屉展示该版原文', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/1', () => HttpResponse.json(V1_DETAIL)))
    renderPage()

    fireEvent.click(await screen.findByTestId('more-menu-stub'))
    fireEvent.click(await screen.findByRole('button', { name: '回看版本 1' }))
    expect(await screen.findByText('版本回看：v1')).toBeInTheDocument()
    // detail 走 react-query 异步加载，Skeleton 先渲染，须等 pre 出现再断言
    expect(await screen.findByTestId('design-version-content')).toHaveTextContent('param width = 60')
  })

  it('版本恢复：确认后恢复旧版为新版本并刷新编辑器', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/1', () => HttpResponse.json(V1_DETAIL)))
    let restored = false
    server.use(http.post('/api/v1/workspaces/10/designs/20/versions/1/restore', () => {
      restored = true
      return HttpResponse.json({ ...DETAIL, content: V1_CONTENT, version_number: 3, version_count: 3 })
    }))
    const { container } = renderPage()

    fireEvent.click(await screen.findByTestId('more-menu-stub'))
    fireEvent.click(await screen.findByRole('button', { name: '回看版本 1' }))
    expect(await screen.findByText('版本回看：v1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /恢复此版本/ }))
    fireEvent.click(screen.getByRole('button', { name: /确\s*定|OK|是/ }))
    await waitFor(() => expect(restored).toBe(true))
    expect(await screen.findByText(/已恢复 v1 为第 3 版/)).toBeInTheDocument()
    // 恢复后的原文同步进编辑器（草稿被替换为恢复内容）
    await waitForEditorReady(container)
    await waitFor(() => expect(cmText(container)).toContain('param width = 60'))
  })

  it('viewer 回看无恢复入口', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({ ...mockWorkspace, id: 10, current_user_role: 'viewer' })))
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/1', () => HttpResponse.json(V1_DETAIL)))
    renderPage()

    fireEvent.click(await screen.findByTestId('more-menu-stub'))
    fireEvent.click(await screen.findByRole('button', { name: '回看版本 1' }))
    expect(await screen.findByText('版本回看：v1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /恢复此版本/ })).not.toBeInTheDocument()
  })

  it('停止输入 3s 后自动保存为 auto 版本（Q1 / D2）', async () => {
    useDefaultHandlers()
    let autoBody: { content: string; change_type?: string } | undefined
    server.use(http.put('/api/v1/workspaces/10/designs/20/content', async ({ request }) => {
      autoBody = await request.json() as { content: string; change_type?: string }
      return HttpResponse.json({ ...DETAIL, content: autoBody.content, version_number: 3, version_count: 3 })
    }))
    const { container } = renderPage()

    await waitForEditorReady(container)
    editViaCodeMirror(container, '\n// 自动保存草稿')
    expect(await screen.findByText('未保存')).toBeInTheDocument()

    await waitFor(() => expect(autoBody).toBeDefined(), { timeout: 6000 })
    expect(autoBody!.change_type).toBe('auto')
    expect(autoBody!.content).toBe(`${CONTENT}\n// 自动保存草稿`)
    // 自动保存成功不回写编辑器（用户可能已继续输入），只提示状态
    expect(cmText(container)).toContain('// 自动保存草稿')
    expect(await screen.findByTestId('design-autosave-status')).toHaveTextContent('已自动保存')
  }, 10000)

  it('自动保存失败只提示状态，不弹错误且草稿保留（I3 / C8）', async () => {
    useDefaultHandlers()
    server.use(http.put('/api/v1/workspaces/10/designs/20/content', () =>
      HttpResponse.json({ detail: '服务暂不可用' }, { status: 500 })))
    const { container } = renderPage()

    await waitForEditorReady(container)
    editViaCodeMirror(container, '\n// 自动保存失败草稿')

    await waitFor(
      () => expect(screen.getByTestId('design-autosave-status')).toHaveTextContent('自动保存失败'),
      { timeout: 6000 },
    )
    expect(screen.queryByText('保存被拒绝（草稿已保留）')).not.toBeInTheDocument()
    expect(cmText(container)).toContain('// 自动保存失败草稿')
  }, 10000)

  it('版本历史：类型徽标 + 连续自动版本折叠可展开（C4）', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions', () => HttpResponse.json([
      { id: 204, design_id: 20, version_number: 4, change_type: 'auto', comment: '', created_by_id: 1, created_at: '2026-10-04T08:00:00Z' },
      { id: 203, design_id: 20, version_number: 3, change_type: 'auto', comment: '', created_by_id: 1, created_at: '2026-10-03T08:00:00Z' },
      ...VERSIONS,
    ])))
    renderPage()

    fireEvent.click(await screen.findByTestId('more-menu-stub'))
    expect((await screen.findAllByText('主动保存')).length).toBe(2)
    const group = screen.getByTestId('design-auto-group-v-4')
    expect(group).toHaveTextContent('2 个自动小版本')
    expect(screen.queryByRole('button', { name: '回看版本 3' })).not.toBeInTheDocument()

    fireEvent.click(group)
    expect(await screen.findByRole('button', { name: '回看版本 3' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '回看版本 4' })).toBeInTheDocument()
  })

  it('版本 DIFF：默认本版 vs 上一版，结构摘要先于文本差异（C5 / C6）', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/2', () => HttpResponse.json({
      ...VERSIONS[0]!,
      content: CONTENT,
      compiled: IR,
      dependencies: [],
    })))
    server.use(http.get('/api/v1/workspaces/10/designs/20/diff', ({ request }) => {
      const url = new URL(request.url)
      const base = Number(url.searchParams.get('base'))
      const head = Number(url.searchParams.get('head'))
      return HttpResponse.json({
        base_version: base,
        head_version: head,
        diff: [
          '--- base',
          '+++ head',
          '@@ -1 +1 @@',
          '-param width = 60',
          '+param width = 80',
          '',
        ].join('\n'),
        added: 1,
        removed: 1,
        summary: {
          available: true,
          params: { added: [], removed: [], changed: [{ name: 'width', base: 60, head: 80 }] },
          nodes: { base: 1, head: 1 },
          assemblies: { added: [], removed: [] },
        },
      })
    }))
    renderPage()

    fireEvent.click(await screen.findByTestId('more-menu-stub'))
    fireEvent.click(await screen.findByRole('button', { name: '回看版本 2' }))
    expect(await screen.findByText('版本回看：v2')).toBeInTheDocument()

    // 默认本版 vs 上一版
    expect(await screen.findByTestId('design-diff-base')).toBeInTheDocument()
    expect(screen.getByTestId('design-diff-head')).toBeInTheDocument()
    // 摘要先于文本差异：参数变化 + 节点数
    const summary = await screen.findByTestId('design-version-diff-summary')
    expect(summary).toHaveTextContent('参数 +0 / -0 / ~1（width）')
    expect(summary).toHaveTextContent('节点 1 → 1')
    const diffView = await screen.findByTestId('document-diff')
    expect(diffView).toHaveTextContent('param width = 80')
    // 摘要先于文本差异（DOM 顺序）
    expect(summary.compareDocumentPosition(diffView) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

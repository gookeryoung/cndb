/** DesignEditorPage 测试 —— 编辑器主流程（ADR 0079 §7）.
 *
 * jsdom 无 WebGL：PreviewCanvas 与 DesignExportMenu 必须 mock（lazy chunk 的
 * 真实渲染与导出由 exporters 单测 + e2e 覆盖）；
 * 编辑器内容变更经 EditorView.findFromDOM 驱动真实 CodeMirror transaction，
 * 覆盖：源码展示 / 诊断回显 / 保存（Ctrl+S）/ 保存失败保留草稿 / 参数面板 overrides /
 * viewer 只读 / 版本回看（P2）/ 版本恢复（P2）.
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { EditorView } from '@codemirror/view'
import { Routes, Route } from 'react-router-dom'
import DesignEditorPage from './DesignEditorPage'
import { renderProviders } from '@/test/render-providers'
import { mockWorkspace, server } from '@/test/msw'
import type {
  DesignDetail, DesignIR, DesignPreviewResult, DesignVersionDetail, DesignVersionItem,
} from '@/api'

const previewCanvas = vi.hoisted(() => vi.fn())
vi.mock('./PreviewCanvas', () => ({
  default: function PreviewCanvasStub({ ir }: { ir: DesignIR | null }) {
    previewCanvas(ir)
    return <div data-testid="preview-canvas-stub">{ir ? `节点数:${ir.nodes.length}` : '空'}</div>
  },
}))

const exportMenu = vi.hoisted(() => vi.fn())
vi.mock('./DesignExportMenu', () => ({
  default: function DesignExportMenuStub({ ir, title }: { ir: DesignIR | null; title: string }) {
    exportMenu({ ir, title })
    return <div data-testid="export-menu-stub">导出:{title}</div>
  },
}))

const AUTH = { initialAuth: { user: null, token: 'fake' } }

const CONTENT = [
  'param width = 80',
  'box(size = [width, 40, 12])',
].join('\n')

const IR: DesignIR = {
  version: 2,
  units: { length: 'mm', angle: 'deg' },
  params: [{ name: 'width', value: 80 }],
  nodes: [{ op: 'box', size: [80, 40, 12] }],
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
  { id: 202, design_id: 20, version_number: 2, comment: '调宽度', created_by_id: 1, created_at: '2026-10-02T08:00:00Z' },
  { id: 201, design_id: 20, version_number: 1, comment: '', created_by_id: 1, created_at: '2026-10-01T08:00:00Z' },
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
  server.use(
    http.get('/api/v1/workspaces/10/designs/20', () => HttpResponse.json(DETAIL)),
    http.get('/api/v1/workspaces/10/designs/20/ir', () =>
      HttpResponse.json({ design_id: 20, version_number: 2, content_hash: 'abc123', ir: IR })),
    http.get('/api/v1/workspaces/10/designs/20/versions', () => HttpResponse.json(VERSIONS)),
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
    // 版本历史：顶部按钮打开侧栏，列表在抽屉内
    expect(screen.getByText('版本历史（2）')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '版本历史' }))
    expect(await screen.findByText('调宽度')).toBeInTheDocument()
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

  it('参数面板从 IR 渲染，改参后 overrides 进入 preview 请求', async () => {
    useDefaultHandlers()
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '参数' }))
    const input = await screen.findByLabelText('参数 width')
    expect((input as HTMLInputElement).value).toBe('80')

    fireEvent.change(input, { target: { value: '100' } })
    await waitFor(() => expect(previewBodies.length).toBeGreaterThan(0))
    expect(previewBodies[previewBodies.length - 1]!.overrides).toEqual({ width: 100 })
    expect(previewBodies[previewBodies.length - 1]!.design_id).toBe(20)
    expect(await screen.findByRole('button', { name: /重置/ })).toBeInTheDocument()
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

  it('P2 版本回看：点击历史版本打开抽屉展示该版原文', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/1', () => HttpResponse.json(V1_DETAIL)))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '版本历史' }))
    fireEvent.click(await screen.findByRole('button', { name: '回看版本 1' }))
    expect(await screen.findByText('版本回看：v1')).toBeInTheDocument()
    // detail 走 react-query 异步加载，Skeleton 先渲染，须等 pre 出现再断言
    expect(await screen.findByTestId('design-version-content')).toHaveTextContent('param width = 60')
  })

  it('P2 版本恢复：确认后恢复旧版为新版本并刷新编辑器', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/1', () => HttpResponse.json(V1_DETAIL)))
    let restored = false
    server.use(http.post('/api/v1/workspaces/10/designs/20/versions/1/restore', () => {
      restored = true
      return HttpResponse.json({ ...DETAIL, content: V1_CONTENT, version_number: 3, version_count: 3 })
    }))
    const { container } = renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '版本历史' }))
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

  it('P2 viewer 回看无恢复入口', async () => {
    useDefaultHandlers()
    server.use(http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({ ...mockWorkspace, id: 10, current_user_role: 'viewer' })))
    server.use(http.get('/api/v1/workspaces/10/designs/20/versions/1', () => HttpResponse.json(V1_DETAIL)))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '版本历史' }))
    fireEvent.click(await screen.findByRole('button', { name: '回看版本 1' }))
    expect(await screen.findByText('版本回看：v1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /恢复此版本/ })).not.toBeInTheDocument()
  })
})

/** 文档知识图谱页测试（需求 0168 C4/C5/C6 + 需求 0182 C3/C5–C9）.
 *
 * 覆盖：节点/边 option 结构（含虚线断链与歧义提示）、单击选中 + 双击进入文档、
 * 局部图 `?focus=&depth=`、筛选栏、图例显隐、Inspector、孤岛/枢纽清单、
 * 力参数面板、标签按倍率淡化、缩放/复位控件、超 500 截断提示。
 * echarts 用轻量 mock，断言 option 纯结构与事件语义。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentGraphPage, {
  collectNeighborhood,
  filterGraph,
  findHubs,
  findIsolated,
  foldReciprocal,
} from './DocumentGraphPage'
import type { GraphEdge, GraphNode } from '@/api/documents'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'

const echartsMock = vi.hoisted(() => {
  const setOption = vi.fn()
  const on = vi.fn()
  const resize = vi.fn()
  const dispose = vi.fn()
  const dispatchAction = vi.fn()
  const getOption = vi.fn(() => ({ series: [{ zoom: 1 }] }))
  const init = vi.fn(() => ({ setOption, on, resize, dispose, dispatchAction, getOption }))
  return { init, setOption, on, resize, dispose, dispatchAction, getOption }
})

vi.mock('echarts/core', () => ({ use: vi.fn(), init: echartsMock.init }))
vi.mock('echarts/charts', () => ({ GraphChart: {} }))
vi.mock('echarts/components', () => ({ TooltipComponent: {} }))
vi.mock('echarts/features', () => ({ LabelLayout: {} }))
vi.mock('echarts/renderers', () => ({ SVGRenderer: {} }))

const graphPayload = {
  nodes: [
    { id: 1, title: '甲', content_type: 'markdown', status: 'published', is_folder: false, broken: false },
    { id: 2, title: '乙', content_type: 'pdf', status: 'published', is_folder: false, broken: false },
    { id: 3, title: '资料夹', content_type: 'folder', status: 'published', is_folder: true, broken: false },
    { id: -123, title: '断链目标', content_type: 'markdown', status: 'broken', is_folder: false, broken: true },
  ],
  edges: [
    { source: 1, target: 2, broken: false, ambiguous: false, raw: '[[乙]]' },
    { source: 1, target: -123, broken: true, ambiguous: true, raw: '[[断链目标]]' },
  ],
  truncated: false,
  total: 4,
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="loc">{`${location.pathname}${location.search}`}</div>
}

function renderPage(route = '/w/10/documents/graph') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/graph" element={<DocumentGraphPage />} />
      <Route path="/w/:wid/documents" element={<LocationProbe />} />
      <Route path="/w/:wid/documents/:docId" element={<div data-testid="editor-stub" />} />
    </Routes>,
    { route, initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

/** 取某个 echarts 事件的最新一次回调 */
function handlerOf(event: string) {
  const found = echartsMock.on.mock.calls.filter((c: unknown[]) => c[0] === event).at(-1)
  return found?.[1] as ((p: unknown) => void) | undefined
}

/** 派发节点点击（value 是文档 id，is_folder 区分文件夹） */
function clickNode(docId: number, isFolder = false) {
  const handler = handlerOf('click')
  act(() => handler?.({ dataType: 'node', data: { value: docId, is_folder: isFolder } }))
}

function doubleClickNode(docId: number, isFolder = false) {
  const handler = handlerOf('dblclick')
  act(() => handler?.({ dataType: 'node', data: { value: docId, is_folder: isFolder } }))
}

/** 节点尺寸：目录节点用 [宽, 高] 表达圆角方形（0184 C9），取宽参与比较 */
function sizeOf(item: { symbolSize?: number | number[] }): number {
  const size = item.symbolSize
  return Array.isArray(size) ? size[0] : (size ?? 0)
}

/** 最近一次「完整图」option：标签显隐是单独一次 setOption 下发的，只带 label 没有 data */
function lastGraphOption() {
  for (let i = echartsMock.setOption.mock.calls.length - 1; i >= 0; i -= 1) {
    const series = echartsMock.setOption.mock.calls[i][0]?.series?.[0]
    if (series && Array.isArray(series.data)) return series
  }
  return undefined
}

describe('知识图谱页（需求 0168 / 0182）', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(graphPayload)),
    )
  })

  it('渲染节点与边：断链用虚线、歧义写入 option', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const option = echartsMock.setOption.mock.calls[0][0]
    const series = option.series[0]
    expect(series.type).toBe('graph')
    expect(series.layout).toBe('force')
    expect(series.data).toHaveLength(4)
    expect(series.links[0].lineStyle.type).toBe('solid')
    expect(series.links[1].lineStyle.type).toBe('dashed')
    expect(series.links[1].ambiguous).toBe(true)
    // echarts 的 SVG 属性不解析 CSS 变量：颜色必须是已解析的具体值
    expect(String(series.links[1].lineStyle.color)).not.toContain('var(')
    expect(String(series.data[3].itemStyle.color)).not.toContain('var(')
    expect(series.data[2].is_folder).toBe(true)

    const tooltip = option.tooltip.formatter({ dataType: 'edge', data: series.links[1] })
    expect(tooltip).toContain('断链')
    expect(tooltip).toContain('同名多文档')
  })

  it('单击只选中、双击才进入文档；文件夹与断链的跳转口径', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    // 需求 0182 C6：单击是「选中」，不能把用户点走
    clickNode(2)
    expect(await screen.findByTestId('graph-inspector-detail')).toBeInTheDocument()
    expect(screen.getByTestId('graph-inspector-title')).toHaveTextContent('乙')
    expect(screen.queryByTestId('editor-stub')).not.toBeInTheDocument()

    doubleClickNode(2)
    expect(await screen.findByTestId('editor-stub')).toBeInTheDocument()

    doubleClickNode(3, true)
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/documents?parent=3'))

    // 断链虚拟节点（负 id）即使双击也不跳转
    doubleClickNode(-123)
    expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/documents?parent=3')
  })

  it('节点标签 formatter 可靠读到标题：series.data 保留 title，标题缺失不抛异常', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const option = echartsMock.setOption.mock.calls[0][0]
    const series = option.series[0]
    // echarts 的 label/tooltip formatter 收到的 params.data 就是这条原始项：
    // 只写 name 时 p.data.title 为 undefined，会以 undefined.length 崩掉整页。
    expect(series.data.map((d: { title?: string }) => d.title)).toEqual(['甲', '乙', '资料夹', '断链目标'])

    const labelFormatter = series.label.formatter as (p: { data?: { title?: string } }) => string
    expect(labelFormatter({ data: series.data[0] })).toBe('甲')
    // 异常响应 / 空标题文档：不能抛错，也不能渲染出 undefined
    expect(labelFormatter({ data: { title: undefined } })).toBe('未命名文档')
    expect(labelFormatter({ data: undefined })).toBe('未命名文档')
    const longTitle = '一个特别特别特别长的文档标题需要被截断掉'
    const truncated = labelFormatter({ data: { title: longTitle } })
    expect(truncated).toBe(`${longTitle.slice(0, 17)}…`)
    expect(truncated).toHaveLength(18)
  })

  it('接口返回缺 nodes/edges 时不崩溃，统计按 0 展示', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () =>
        HttpResponse.json({ truncated: false, total: 0 }),
      ),
    )
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 0 / 共 0 个节点 · 关系 0'),
    )
    await waitFor(() => expect(lastGraphOption()?.data).toEqual([]))
    expect(lastGraphOption()?.links).toEqual([])
  })

  it('超出节点上限时显示截断提示，并区分「指向图外的关系」与断链（C2）', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () =>
        HttpResponse.json({ ...graphPayload, truncated: true, total: 612, edges_out_of_view: 7 }),
      ),
    )
    renderPage()
    const alert = await screen.findByTestId('graph-truncated-alert')
    expect(alert).toHaveTextContent('仅展示最近更新的 500 个')
    expect(alert).toHaveTextContent('共 612 个')
    expect(alert).toHaveTextContent('另有 7 条关系指向未展示的文档')
  })

  /**
   * 缩放语义回归（H12）：
   * echarts 的 graphRoam 是相对增量，且缺 originX/originY 时以左上角为锚点，
   * 曾导致点「放大」整张图飞出画布、SVG 里出现 NaN。
   */
  it('缩放动作以画布中心为锚点，并限制在 0.25×–4× 区间', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    // jsdom 不做布局，显式给出画布尺寸，锚点应等于其中心
    const canvas = screen.getByTestId('document-graph-canvas')
    Object.defineProperty(canvas, 'clientWidth', { configurable: true, value: 800 })
    Object.defineProperty(canvas, 'clientHeight', { configurable: true, value: 600 })

    fireEvent.click(screen.getByTestId('graph-zoom-in'))
    const zoomIn = echartsMock.dispatchAction.mock.calls.at(-1)?.[0]
    expect(zoomIn).toMatchObject({ type: 'graphRoam', zoom: 1.25, originX: 400, originY: 300 })
    expect(Number.isNaN(zoomIn.originX)).toBe(false)
    expect(Number.isNaN(zoomIn.originY)).toBe(false)
    expect(screen.getByTestId('graph-zoom-pct')).toHaveTextContent('125%')

    fireEvent.click(screen.getByTestId('graph-zoom-out'))
    expect(echartsMock.dispatchAction.mock.calls.at(-1)?.[0]).toMatchObject({ zoom: 0.8, originX: 400, originY: 300 })
    expect(screen.getByTestId('graph-zoom-pct')).toHaveTextContent('100%')
  })

  it('到达缩放上下限时停止派发并禁用按钮', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const zoomIn = screen.getByTestId('graph-zoom-in')
    const zoomOut = screen.getByTestId('graph-zoom-out')

    // 连点放大到 4×：19 次 ×1.25 ≈ 4.0 后停住
    for (let i = 0; i < 25; i += 1) fireEvent.click(zoomIn)
    const pct = screen.getByTestId('graph-zoom-pct')
    expect(pct).toHaveTextContent('400%')
    expect(zoomIn).toBeDisabled()
    const callsAtMax = echartsMock.dispatchAction.mock.calls.length
    fireEvent.click(zoomIn)
    expect(echartsMock.dispatchAction.mock.calls.length).toBe(callsAtMax)

    // 反向到 0.25×
    for (let i = 0; i < 40; i += 1) fireEvent.click(zoomOut)
    expect(pct).toHaveTextContent('25%')
    expect(zoomOut).toBeDisabled()
  })

  it('视图 option 具备同类图谱应用的显示要素：缩放上下限、标签避让、方向箭头、度数分级', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const series = echartsMock.setOption.mock.calls[0][0].series[0]
    expect(series.roam).toBe(true)
    expect(series.scaleLimit).toEqual({ min: 0.25, max: 4 })
    expect(series.labelLayout.hideOverlap).toBe(true)
    expect(series.edgeSymbol).toEqual(['none', 'arrow'])
    // 缩放时节点不完全跟随倍数膨胀，避免放大后节点糊住标签
    expect(series.nodeScaleRatio).toBeLessThan(1)
    // 悬停只高亮邻接
    expect(series.emphasis.focus).toBe('adjacency')
    expect(series.blur.itemStyle.opacity).toBeLessThan(0.5)

    // 度数分级：甲连了 2 条边，孤立文件夹 0 条，前者必须更大
    expect(sizeOf(series.data[0])).toBeGreaterThan(sizeOf(series.data[2]))
    // 需求 0184 C3：孤立点（非断链且度 0）在画布上退到 10px
    expect(sizeOf(series.data[2])).toBe(10)
    expect(series.data.every((d: { symbolSize?: number | number[] }) => sizeOf(d) <= 40)).toBe(true)
  })

  it('滚轮缩放后倍率读数跟随视图（graphroam 事件）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    const roamHandler = handlerOf('graphroam')
    expect(roamHandler).toBeTypeOf('function')

    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 2.5 }] })
    act(() => roamHandler?.(undefined))
    expect(screen.getByTestId('graph-zoom-pct')).toHaveTextContent('250%')

    // 越界的视图倍率按上下限夹住，读数不出现 0% 或 1000%
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 100 }] })
    act(() => roamHandler?.(undefined))
    expect(screen.getByTestId('graph-zoom-pct')).toHaveTextContent('400%')
  })

  it('局部图按 ?focus=&depth= 收敛节点集，中心文档不在图内时给出回退入口（C3）', async () => {
    renderPage('/w/10/documents/graph?focus=1&depth=1')
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()

    // 1 的 1 跳邻域 = {1, 2, -123}：出链与反链都算邻接
    await waitFor(() => expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 3 / 共 4 个节点'))
    expect(screen.getByTestId('graph-focus-tag')).toHaveTextContent('甲')
    expect(screen.getByTestId('graph-focus-tag')).toHaveTextContent('1 跳')
  })

  it('中心文档不在图内时提示并可一键回到全图（C3）', async () => {
    renderPage('/w/10/documents/graph?focus=999&depth=1')
    expect(await screen.findByText(/作为中心的文档不在当前图谱范围内/)).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('graph-clear-focus'))
    expect(await screen.findByText('显示 4 / 共 4', { exact: false })).toBeInTheDocument()
    expect(screen.queryByTestId('graph-focus-tag')).not.toBeInTheDocument()
  })

  it('筛选栏按关键词与只看断链收敛，页脚同时给出「显示 X / 共 Y」（C5）', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    expect(await screen.findByText('显示 4 / 共 4', { exact: false })).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('graph-filter-keyword'), { target: { value: '资' } })
    await waitFor(() => expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 1 / 共 4'))
    expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('隐藏 3')

    fireEvent.change(screen.getByTestId('graph-filter-keyword'), { target: { value: '' } })
    expect(await screen.findByText('显示 4 / 共 4', { exact: false })).toBeInTheDocument()

    // 只看断链：保留断链节点与「指向它的源节点」，否则画出来是一堆孤点
    fireEvent.click(screen.getByTestId('graph-filter-broken'))
    expect(await screen.findByText('显示 2 / 共 4', { exact: false })).toBeInTheDocument()
    await waitFor(() => expect(lastGraphOption()?.data).toHaveLength(2))
  })

  it('图例按格式显隐，关掉某项后画布与图例状态同步（C7）', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    expect(await screen.findByTestId('graph-legend-pdf')).toBeInTheDocument()

    expect(screen.getByTestId('graph-legend-pdf')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByTestId('graph-legend-pdf'))
    await waitFor(() => expect(screen.getByTestId('graph-legend-pdf')).toHaveAttribute('aria-pressed', 'false'))
    expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 3 / 共 4')

    fireEvent.click(screen.getByTestId('graph-legend-pdf'))
    expect(await screen.findByText('显示 4 / 共 4', { exact: false })).toBeInTheDocument()
  })

  it('标签按缩放倍率淡化，工具栏可整体开关（C7）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const labelShows = () =>
      echartsMock.setOption.mock.calls.at(-1)?.[0]?.series?.[0]?.label?.show as boolean | undefined
    await waitFor(() => expect(labelShows()).toBe(true))

    // 0.8^3 ≈ 51%，低于 60% 阈值
    for (let i = 0; i < 3; i += 1) fireEvent.click(screen.getByTestId('graph-zoom-out'))
    await waitFor(() => expect(labelShows()).toBe(false))

    // 0189 C5：标签开关下沉到画布视图控制簇，用图标按钮 + aria-label 表达状态
    const labelToggle = screen.getByTestId('graph-labels-toggle')
    expect(labelToggle).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(labelToggle)
    expect(screen.getByTestId('graph-labels-toggle')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByTestId('graph-labels-toggle')).toHaveAttribute('aria-label', '显示标签')
  })

  it('Inspector 展示选中文档的出链/反链，并可打开文档、设为中心、复制链接（C6）', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })

    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    clickNode(1)
    expect(await screen.findByTestId('graph-inspector-detail')).toBeInTheDocument()
    const detail = screen.getByTestId('graph-inspector-detail')
    expect(detail).toHaveTextContent('出链 2')
    expect(detail).toHaveTextContent('反链 0')
    expect(detail).toHaveTextContent('关联 2 条')

    fireEvent.click(screen.getByTestId('graph-inspector-copy'))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('/w/10/documents/graph?focus=1')))

    fireEvent.click(screen.getByTestId('graph-inspector-focus'))
    await waitFor(() => expect(screen.getByTestId('graph-focus-tag')).toHaveTextContent('甲'))

    fireEvent.click(screen.getByTestId('graph-inspector-open'))
    expect(await screen.findByTestId('editor-stub')).toBeInTheDocument()

    vi.unstubAllGlobals()
  })

  it('未选中时 Inspector 给出孤岛与枢纽清单，点击可定位（C8）', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()

    // 资料夹（id 3）没有任何边 → 孤岛；甲度数最高 → 枢纽首位
    const isolated = await screen.findByTestId('graph-isolated-list')
    expect(isolated).toHaveTextContent('资料夹')
    const hubs = screen.getByTestId('graph-hub-list')
    expect(hubs.firstElementChild).toHaveTextContent('甲')

    fireEvent.click(hubs.querySelector('a') as HTMLElement)
    await waitFor(() => expect(screen.getByTestId('graph-inspector-title')).toHaveTextContent('甲'))
  })

  it('力参数面板可调斥力并恢复默认（C9）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    // 标签显隐是单独一次 setOption 下发的（只带 label），力参数要看最近带 force 的那次
    const forceOf = () => {
      for (let i = echartsMock.setOption.mock.calls.length - 1; i >= 0; i -= 1) {
        const force = echartsMock.setOption.mock.calls[i][0]?.series?.[0]?.force
        if (force) return force
      }
      return undefined
    }
    // 需求 0184 C12：默认斥力 220（仍在 0182 C9 的 40–600 滑轨内），边长摊成区间
    expect(forceOf()).toMatchObject({ repulsion: 220, edgeLength: [60, 140], gravity: 0.08 })

    // 0189 C5 / C9：力参数从 Inspector 搬到画布右下控制簇，由「布局」按钮展开
    fireEvent.click(screen.getByTestId('graph-force-toggle'))
    const slider = (await screen.findByTestId('graph-force-repulsion-wrap')).querySelector('[role="slider"]') as HTMLElement
    // rc-slider 的键盘处理读 keyCode（antd 6 / rc-slider 11），只给 key 不会触发
    fireEvent.keyDown(slider, { key: 'ArrowRight', keyCode: 39, which: 39 })
    await waitFor(() => expect(forceOf().repulsion).toBe(240))

    fireEvent.click(screen.getByTestId('graph-force-reset'))
    await waitFor(() => expect(forceOf()).toMatchObject({ repulsion: 220, edgeLength: [60, 140], gravity: 0.08 }))
  })

  it('编辑器深链：?focus=2 直接以该文档为中心打开', async () => {
    renderPage('/w/10/documents/graph?focus=2&depth=1')
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    expect(await screen.findByText('显示 2 / 共 4', { exact: false })).toBeInTheDocument()
    expect(screen.getByTestId('graph-focus-tag')).toHaveTextContent('乙')
  })
})

/** 判定层纯函数：这些是「漏跑就画错图」的逻辑，单独钉住 */
describe('图谱判定纯函数（需求 0182）', () => {
  const nodes: GraphNode[] = [
    { id: 1, title: '甲', content_type: 'markdown', status: 'published', is_folder: false, broken: false },
    { id: 2, title: '乙', content_type: 'pdf', status: 'draft', is_folder: false, broken: false },
    { id: 3, title: '丙', content_type: 'markdown', status: 'published', is_folder: false, broken: false },
    { id: -9, title: '缺', content_type: 'markdown', status: 'broken', is_folder: false, broken: true },
  ]
  const edges: GraphEdge[] = [
    { source: 1, target: 2, broken: false, ambiguous: false, raw: '[[乙]]' },
    { source: 1, target: 3, broken: false, ambiguous: false, raw: '[[丙]]' },
    { source: 3, target: -9, broken: true, ambiguous: false, raw: '[[缺]]' },
  ]
  const degrees = new Map<number, number>([[1, 2], [2, 1], [3, 2], [-9, 1]])
  const noDeps = { scope: null, hiddenFormats: new Set<string>(), degrees }

  it('collectNeighborhood 按无向邻接扩跳：反链也算邻接', () => {
    // 只看出链时 2 不会把 1 带出来
    expect([...collectNeighborhood(edges, 2, 1)].sort()).toEqual([1, 2])
    expect([...collectNeighborhood(edges, 1, 1)].sort()).toEqual([1, 2, 3])
    expect([...collectNeighborhood(edges, 1, 2)].sort((a, b) => a - b)).toEqual([-9, 1, 2, 3])
    // depth 落到 0 时退化为只有自己
    expect([...collectNeighborhood(edges, 1, 0)]).toEqual([1])
  })

  it('filterGraph 多条件同时生效，且边只留两端都可见的', () => {
    const byKeyword = filterGraph(
      nodes,
      edges,
      { keyword: '丙', statuses: [], onlyBroken: false, onlyIsolated: false },
      noDeps,
    )
    expect(byKeyword.nodes.map(n => n.id)).toEqual([3])
    expect(byKeyword.edges).toEqual([])

    const byStatus = filterGraph(
      nodes,
      edges,
      { keyword: '', statuses: ['draft'], onlyBroken: false, onlyIsolated: false },
      noDeps,
    )
    // 断链节点没有状态字段，按状态筛时不能被误杀（否则「草稿」筛选会把所有断链藏掉）
    expect(byStatus.nodes.map(n => n.id)).toEqual([2, -9])

    const byScope = filterGraph(
      nodes,
      edges,
      { keyword: '', statuses: [], onlyBroken: false, onlyIsolated: false },
      { ...noDeps, scope: new Set([1, 2]) },
    )
    expect(byScope.nodes.map(n => n.id)).toEqual([1, 2])
    expect(byScope.edges.map(e => `${e.source}->${e.target}`)).toEqual(['1->2'])

    const byFormat = filterGraph(
      nodes,
      edges,
      { keyword: '', statuses: [], onlyBroken: false, onlyIsolated: false },
      { ...noDeps, hiddenFormats: new Set(['pdf']) },
    )
    expect(byFormat.nodes.map(n => n.id)).toEqual([1, 3, -9])

    // 只看断链：断链节点 + 指向它的源节点都要留，否则画出来是一堆孤点
    const broken = filterGraph(
      nodes,
      edges,
      { keyword: '', statuses: [], onlyBroken: true, onlyIsolated: false },
      noDeps,
    )
    expect(broken.nodes.map(n => n.id).sort((a, b) => a - b)).toEqual([-9, 3])
    expect(broken.edges.map(e => `${e.source}->${e.target}`)).toEqual(['3->-9'])
  })

  it('findIsolated / findHubs 排除断链节点，枢纽按度数倒序且不含零度', () => {
    expect(findIsolated(nodes, degrees).map(n => n.id)).toEqual([])
    expect(findIsolated(nodes, new Map([[-9, 0], [1, 0], [2, 1], [3, 0]])).map(n => n.id)).toEqual([1, 3])
    const hubs = findHubs(nodes, degrees)
    expect(hubs.map(n => n.id)).toEqual([1, 3, 2])
    expect(findHubs(nodes, degrees, 1).map(n => n.id)).toEqual([1])
  })
})

/** 需求 0183：互引折叠成一条线、两端箭头表义、箭头显隐开关 */
describe('图谱单双向边表达（需求 0183）', () => {
  const mutualPayload = {
    nodes: [
      { id: 1, title: '甲', content_type: 'markdown', status: 'published', is_folder: false, broken: false },
      { id: 2, title: '乙', content_type: 'markdown', status: 'published', is_folder: false, broken: false },
      { id: 3, title: '丙', content_type: 'markdown', status: 'published', is_folder: false, broken: false },
    ],
    edges: [
      { source: 1, target: 2, broken: false, ambiguous: false, raw: '[[乙]]' },
      // 反向边：与上一条构成互引（C1）
      { source: 2, target: 1, broken: false, ambiguous: false, raw: '[[甲]]' },
      { source: 1, target: 3, broken: false, ambiguous: false, raw: '[[丙]]' },
    ],
    truncated: false,
    total: 3,
  }

  /** 箭头显隐是单独一次 setOption 下发的：只带 edgeSymbol，不带 data */
  const lastArrowOption = () => {
    for (let i = echartsMock.setOption.mock.calls.length - 1; i >= 0; i -= 1) {
      const series = echartsMock.setOption.mock.calls[i][0]?.series?.[0]
      if (series && 'edgeSymbol' in series && !Array.isArray(series.data)) return series
    }
    return undefined
  }

  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(graphPayload)),
    )
  })

  it('foldReciprocal 合并互引、双向标记、断链与歧义取并集（C1）', () => {
    const folded = foldReciprocal([
      { source: 2, target: 1, broken: false, ambiguous: false, raw: '[[甲]]' },
      { source: 1, target: 2, broken: true, ambiguous: true, raw: '[[乙]]' },
      { source: 1, target: 3, broken: false, ambiguous: false, raw: '[[丙]]' },
    ])
    expect(folded).toHaveLength(2)
    const mutual = folded[0]
    expect(mutual.mutual).toBe(true)
    expect([mutual.source, mutual.target]).toEqual([2, 1])
    expect(mutual.raw).toBe('[[甲]]')
    expect(mutual.reverseRaw).toBe('[[乙]]')
    // 任一方向断链 / 歧义即整体成立：折叠后只剩一条线可着色
    expect(mutual.broken).toBe(true)
    expect(mutual.ambiguous).toBe(true)
    // 单向边不折叠、不带反向原文
    expect(folded[1].mutual).toBe(false)
    expect(folded[1].reverseRaw).toBeUndefined()
  })

  it('互引只画一条线：两端箭头 + 页脚互引计数 + tooltip 提示（C1/C2/C4/C6）', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(mutualPayload)),
    )
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const option = echartsMock.setOption.mock.calls[0][0]
    const series = option.series[0]
    // 三条有向边 → 两条线（互引合并）
    expect(series.links).toHaveLength(2)
    expect(series.edgeSymbol).toEqual(['none', 'arrow'])

    const mutual = series.links.find((link: { mutual?: boolean }) => link.mutual === true)
    expect(mutual.symbol).toEqual(['arrow', 'arrow'])
    // 单向边沿用 series 默认，不额外下发 symbol
    const single = series.links.find((link: { mutual?: boolean }) => !link.mutual)
    expect(single.symbol).toBeUndefined()

    const tooltip = option.tooltip.formatter({ dataType: 'edge', data: mutual })
    expect(tooltip).toContain('互相引用')
    expect(tooltip).toContain('[[甲]]')

    expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('关系 2（互引 1）')
  })

  it('度数按唯一关联数算：互引不重复计数（C3）', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(mutualPayload)),
    )
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    clickNode(1)
    const detail = await screen.findByTestId('graph-inspector-detail')
    // 有向 3 条（1→2、2→1、1→3），唯一邻居只有 2 和 3
    expect(detail).toHaveTextContent('关联 2 条')
    // Inspector 仍给有向明细，互引条目补角标（D6）
    expect(detail).toHaveTextContent('出链 2')
    expect(detail).toHaveTextContent('反链 1')
    expect(detail).toHaveTextContent('⇄ 互引')
  })

  it('箭头开关与低倍率自动收起都走独立 setOption（C7）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const toggle = screen.getByTestId('graph-arrows-toggle')
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveAttribute('aria-label', '隐藏箭头')
    await waitFor(() => expect(lastArrowOption()?.edgeSymbol).toEqual(['none', 'arrow']))

    fireEvent.click(toggle)
    await waitFor(() => expect(lastArrowOption()?.edgeSymbol).toBe('none'))
    // 关掉箭头时尺寸同时归零，避免只剩无法命中的空 symbol 占位
    expect(lastArrowOption()?.edgeSymbolSize).toBe(0)
    expect(screen.getByTestId('graph-arrows-toggle')).toHaveAttribute('aria-label', '显示箭头')

    // 重新打开后缩放：0.8^5 ≈ 33%，低于 40% 阈值自动收起箭头
    fireEvent.click(screen.getByTestId('graph-arrows-toggle'))
    await waitFor(() => expect(lastArrowOption()?.edgeSymbol).toEqual(['none', 'arrow']))
    for (let i = 0; i < 5; i += 1) fireEvent.click(screen.getByTestId('graph-zoom-out'))
    await waitFor(() => expect(lastArrowOption()?.edgeSymbol).toBe('none'))
  })

  it('图例给出单双向说明项，且不参与格式显隐（C5）', async () => {
    renderPage()
    // 先等数据落地，否则页脚还是空图的 0 / 0
    expect(await screen.findByText('显示 4 / 共 4', { exact: false })).toBeInTheDocument()
    expect(await screen.findByTestId('graph-legend-edge-direction')).toBeInTheDocument()
    const note = screen.getByTestId('graph-legend-edge-direction')
    // 说明项不是按钮：点它不应触发任何格式过滤
    expect(note.tagName).toBe('SPAN')
    expect(note).not.toHaveAttribute('aria-pressed')
    expect(note).toHaveTextContent('互引')
    fireEvent.click(note)
    expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 4 / 共 4')
  })
})

describe('图谱视觉打磨（需求 0184 P0）', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(graphPayload)),
    )
  })

  it('孤立点在画布上淡化并隐藏标签，侧栏清单仍保留（C3）', async () => {
    renderPage()
    expect(await screen.findByTestId('document-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const series = lastGraphOption()
    const isolated = series.data[2]
    // 资料夹是目录节点：符号是圆角方形，尺寸写成 [宽, 高]（C9），取宽比较
    expect(sizeOf(isolated)).toBe(10)
    expect(isolated.itemStyle.opacity).toBeLessThan(0.5)
    expect(isolated.label.show).toBe(false)
    expect(isolated.isolated).toBe(true)
    // 0182 C8 的孤岛清单不受影响：画布淡化不等于功能移除
    expect(screen.getByTestId('graph-isolated-list')).toHaveTextContent('资料夹')
  })

  it('边默认弱化：线细且淡，断链仍用 error 色虚线（C6）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const series = lastGraphOption()
    const solid = series.links[0]
    expect(solid.lineStyle.type).toBe('solid')
    expect(solid.lineStyle.width).toBe(1)
    expect(solid.lineStyle.opacity).toBeLessThan(0.4)

    const broken = series.links[1]
    expect(broken.lineStyle.type).toBe('dashed')
    // 断链靠形状 + 颜色双通道，不靠加粗争权重
    expect(broken.lineStyle.width).toBe(1)
    expect(String(broken.lineStyle.color)).not.toContain('var(')
  })

  it('标签底衬只给度数 ≥2 的节点，其余保持透明（C7）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    const series = lastGraphOption()
    // 甲有两条出链，交叉边最密，给它底衬
    expect(series.data[0].label.backgroundColor).toBeTruthy()
    expect(series.data[0].label.backgroundColor).not.toBe('transparent')
    // 乙只有一条边，不加底衬，免得满屏小方块
    expect(series.data[1].label.backgroundColor).toBe('transparent')
    expect(series.data[0].label.padding).toEqual([2, 4])
  })

  it('单击选中：选中节点加描边与投影，非邻接节点被压暗（C1/C2）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    const before = lastGraphOption()
    const idleBorder = before.data[0].itemStyle.borderColor
    const idleSize = before.data[0].symbolSize

    clickNode(1)
    await waitFor(() => expect(lastGraphOption()?.data?.[0]?.selected).toBe(true))

    const after = lastGraphOption()
    // 选中节点：描边换成主色 + 投影 + 轻微放大，填充色不动（格式色仍是主信息）
    expect(after.data[0].itemStyle.borderColor).not.toBe(idleBorder)
    expect(after.data[0].itemStyle.borderWidth).toBe(2)
    expect(after.data[0].itemStyle.shadowBlur).toBeGreaterThan(0)
    expect(after.data[0].symbolSize).toBeGreaterThan(idleSize)
    expect(after.data[0].symbolSize).toBeLessThanOrEqual(40)

    // 非邻接节点压暗，但仍在画布上（保留位置线索）
    expect(after.data[2].itemStyle.opacity).toBeLessThan(0.2)
    // 邻接边加粗加亮，非邻接边几乎看不见
    expect(after.links[0].lineStyle.width).toBeGreaterThan(before.links[0].lineStyle.width)
    expect(after.links[0].lineStyle.opacity).toBeGreaterThan(before.links[0].lineStyle.opacity)
  })

  it('点画布空白处取消选中，视图回到常态（C2）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    clickNode(1)
    await waitFor(() => expect(lastGraphOption()?.data?.[0]?.selected).toBe(true))

    const clickHandler = handlerOf('click')
    act(() => clickHandler?.({ dataType: 'series', data: { value: 1 } }))
    await waitFor(() => expect(lastGraphOption()?.data?.[0]?.selected).toBe(false))
    // 取消后不再是「选中态」，节点回到默认透明度
    expect(lastGraphOption()?.data?.[2]?.itemStyle?.opacity).toBeGreaterThan(0.3)
  })
})
describe('图谱布局稳定与画布纹理（需求 0184 P2）', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(graphPayload)),
    )
  })

  it('力导向从环形初值起步、开布局动画，边长为区间值（C12）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    // 随机初值每次收敛结果不同，重建后图形会「换一张脸」：初值必须是确定性布局
    const series = echartsMock.setOption.mock.calls[0][0].series[0]
    expect(series.force.initLayout).toBe('circular')
    expect(series.force.edgeLength).toEqual([60, 140])
    expect(series.layoutAnimation).toBe(true)
  })

  it('option 更新走 merge，避免每次选中都让力导向重排（C12）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1))

    clickNode(1)
    await waitFor(() => {
      const calls = echartsMock.setOption.mock.calls
      const withData = calls.filter(call => Array.isArray(call[0]?.series?.[0]?.data))
      expect(withData.length).toBeGreaterThan(1)
    })

    // 主 option 的每一次下发都必须传 merge=false 组合（第二参数 false），不能 notMerge
    const mainCalls = echartsMock.setOption.mock.calls
      .filter(call => Array.isArray(call[0]?.series?.[0]?.data))
    expect(mainCalls.every(call => call[1] === false)).toBe(true)
  })

  it('画布用点阵网格背景，且不新增主题变量（C13）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')

    // 0189 C7：画布高度与边框已全部交给样式表，不再有任何内联尺寸 / 边框
    const canvas = screen.getByTestId('document-graph-canvas')
    expect(canvas.style.background).toBe('')
    expect(canvas.getAttribute('style')).toBeNull()
  })
})

/** 需求 0189：版式分层（页头 / 筛选条 / 画布 / Inspector）与空载态 */
describe('知识图谱版式与空载态（需求 0189）', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () => HttpResponse.json(graphPayload)),
    )
  })

  it('C4：页头只有身份信息，画布动作全部下沉到画布内控制簇', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')

    const page = screen.getByTestId('document-graph-page')
    const head = page.querySelector('.cn-page-head') as HTMLElement
    expect(head).toBeTruthy()
    // 页头不再有动作区：6 个视图控件都搬进画布
    expect(head.querySelector('.cn-page-head-actions')).toBeNull()
    for (const id of ['graph-zoom-in', 'graph-zoom-out', 'graph-labels-toggle', 'graph-reset', 'graph-force-toggle']) {
      expect(head.contains(screen.getByTestId(id)), `${id} 不应在页头`).toBe(false)
    }
    // 控制簇是画布容器的子节点（浮动在画布右下）
    const controls = screen.getByTestId('graph-view-controls')
    expect(controls.closest('.cn-graph-canvas-wrap')).toBeTruthy()
    expect(controls.contains(screen.getByTestId('graph-zoom-in'))).toBe(true)
    expect(controls.contains(screen.getByTestId('graph-force-toggle'))).toBe(true)
  })

  it('C6：读数与筛选控件同屏（筛选条右端），页脚不再重复一份', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')

    const bar = screen.getByTestId('graph-filter-bar')
    const stats = screen.getByTestId('graph-footer-stats')
    expect(bar.contains(stats)).toBe(true)
    expect(bar.contains(screen.getByTestId('graph-filter-keyword'))).toBe(true)
    // 全文只有一处读数
    expect(screen.getAllByTestId('graph-footer-stats')).toHaveLength(1)
    await waitFor(() => expect(stats).toHaveTextContent('显示 4 / 共 4'))
  })

  it('C5 / C9：力参数面板在画布控制簇内，不在 Inspector 里', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')

    // 默认收起
    expect(screen.queryByTestId('graph-force-panel')).toBeNull()
    fireEvent.click(screen.getByTestId('graph-force-toggle'))
    const panel = await screen.findByTestId('graph-force-panel')
    expect(screen.getByTestId('graph-view-controls').contains(panel)).toBe(true)
    expect(screen.getByTestId('graph-inspector').contains(panel)).toBe(false)

    // 收起后回到画布本体
    fireEvent.click(screen.getByTestId('graph-force-toggle'))
    await waitFor(() => expect(screen.queryByTestId('graph-force-panel')).toBeNull())
  })

  it('C8：图例可收起，收起后格式 chip 隐藏但显隐状态保留', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    expect(await screen.findByTestId('graph-legend-pdf')).toBeInTheDocument()

    // 先关掉 PDF，再收起图例
    fireEvent.click(screen.getByTestId('graph-legend-pdf'))
    await waitFor(() =>
      expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 3 / 共 4'),
    )

    fireEvent.click(screen.getByTestId('graph-legend-toggle'))
    await waitFor(() => expect(screen.queryByTestId('graph-legend-pdf')).toBeNull())
    // 收起不改变筛选结果：PDF 仍然是关掉的
    expect(screen.getByTestId('graph-footer-stats')).toHaveTextContent('显示 3 / 共 4')
    expect(screen.getByTestId('graph-legend-toggle')).toHaveAttribute('aria-expanded', 'false')

    // 再展开：状态延续
    fireEvent.click(screen.getByTestId('graph-legend-toggle'))
    const pdf = await screen.findByTestId('graph-legend-pdf')
    expect(pdf).toHaveAttribute('aria-pressed', 'false')
  })

  it('C10：空工作区给出空态与「去新建文档」入口，不是一张空白画布', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () =>
        HttpResponse.json({ nodes: [], edges: [], truncated: false, total: 0 }),
      ),
    )
    renderPage()
    const empty = await screen.findByTestId('graph-empty-state')
    expect(empty).toHaveTextContent('还没有文档')
    // 空态压在画布上方，画布本身仍挂载（echarts 初始化不受影响）
    expect(screen.getByTestId('document-graph-canvas')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '去新建文档' }))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/documents'))
  })

  it('C10：请求未返回时给出加载态，数据到达后消失', async () => {
    renderPage()
    expect(await screen.findByTestId('graph-loading-state')).toHaveTextContent('正在加载知识图谱')
    await waitFor(() => expect(screen.queryByTestId('graph-loading-state')).toBeNull())
    expect(screen.queryByTestId('graph-empty-state')).toBeNull()
  })

  it('C11：提示条不再自带 marginBottom，纵向节奏交给 .cn-page 的 gap', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () =>
        HttpResponse.json({ ...graphPayload, truncated: true, total: 612 }),
      ),
    )
    renderPage()
    const alert = await screen.findByTestId('graph-truncated-alert')
    expect(alert.getAttribute('style') ?? '').not.toContain('margin')
  })

  it('C7：页面根容器用 .cn-page + .cn-graph-page 修饰类（高度撑满，不改全局）', async () => {
    renderPage()
    const page = await screen.findByTestId('document-graph-page')
    expect(page).toHaveClass('cn-page')
    expect(page).toHaveClass('cn-graph-page')
  })
})

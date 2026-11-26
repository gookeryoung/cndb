/** 文档知识图谱页测试（需求 0168 C4/C5/C6）.
 *
 * 覆盖：节点/边 option 结构（含虚线断链与歧义提示）、点击节点跳转、
 * 缩放/复位控件、超 500 截断提示。echarts 用轻量 mock，断言 option 纯结构。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import DocumentGraphPage from './DocumentGraphPage'
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

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/documents/graph" element={<DocumentGraphPage />} />
      <Route path="/w/:wid/documents" element={<LocationProbe />} />
      <Route path="/w/:wid/documents/:docId" element={<div data-testid="editor-stub" />} />
    </Routes>,
    { route: '/w/10/documents/graph', initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

describe('知识图谱页（需求 0168）', () => {
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

  it('点击文档节点进编辑器、文件夹节点进目录列表，缩放与复位调用 dispatchAction', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())
    const clickHandler = echartsMock.on.mock.calls.find((c: unknown[]) => c[0] === 'click')?.[1] as
      | ((p: { dataType: string; data: { value: number; is_folder?: boolean } }) => void)
      | undefined
    expect(clickHandler).toBeTypeOf('function')

    // 缩放/复位需在图谱页仍在挂载时触发
    fireEvent.click(screen.getByTestId('graph-zoom-in'))
    fireEvent.click(screen.getByTestId('graph-zoom-out'))
    fireEvent.click(screen.getByTestId('graph-reset'))
    expect(echartsMock.dispatchAction).toHaveBeenCalledTimes(3)

    act(() => clickHandler?.({ dataType: 'node', data: { value: 2 } }))
    expect(await screen.findByTestId('editor-stub')).toBeInTheDocument()

    act(() => clickHandler?.({ dataType: 'node', data: { value: 3, is_folder: true } }))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/documents?parent=3'))

    // 断链虚拟节点（负 id）不跳转：位置保持在上一次跳转结果
    clickHandler?.({ dataType: 'node', data: { value: -123 } })
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
    expect(screen.getByText(/节点 0 · 关系 0/)).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.setOption).toHaveBeenCalled())
    const option = echartsMock.setOption.mock.calls.at(-1)?.[0]
    expect(option.series[0].data).toEqual([])
    expect(option.series[0].links).toEqual([])
  })

  it('超出节点上限时显示截断提示', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/documents/links/graph', () =>
        HttpResponse.json({ ...graphPayload, truncated: true, total: 612 }),
      ),
    )
    renderPage()
    expect(await screen.findByText(/仅展示最近更新的 500 个/)).toBeInTheDocument()
    expect(screen.getByText(/共 612 个/)).toBeInTheDocument()
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
    expect(series.data[0].symbolSize).toBeGreaterThan(series.data[2].symbolSize)
    expect(series.data[2].symbolSize).toBe(14)
    expect(series.data.every((d: { symbolSize: number }) => d.symbolSize <= 40)).toBe(true)
  })

  it('滚轮缩放后倍率读数跟随视图（graphroam 事件）', async () => {
    renderPage()
    await screen.findByTestId('document-graph-canvas')
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    const roamHandler = echartsMock.on.mock.calls.find((c: unknown[]) => c[0] === 'graphroam')?.[1] as
      | (() => void)
      | undefined
    expect(roamHandler).toBeTypeOf('function')

    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 2.5 }] })
    act(() => roamHandler?.())
    expect(screen.getByTestId('graph-zoom-pct')).toHaveTextContent('250%')

    // 越界的视图倍率按上下限夹住，读数不出现 0% 或 1000%
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 100 }] })
    act(() => roamHandler?.())
    expect(screen.getByTestId('graph-zoom-pct')).toHaveTextContent('400%')
  })

})

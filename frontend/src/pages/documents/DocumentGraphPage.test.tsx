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
  const init = vi.fn(() => ({ setOption, on, resize, dispose, dispatchAction }))
  return { init, setOption, on, resize, dispose, dispatchAction }
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
})

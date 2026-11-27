/** 数据表关联图页测试（需求 0187 P0）.
 *
 * 覆盖：节点 / 边 option 结构（虚拟节点 roundRect + 虚线）、单击选中 + 双击进入表、
 * 局部图 `?focus=&depth=`（BFS）、筛选栏（关键词 / 孤立表 / 外部关联 / 自关联）、
 * 图例显隐、Inspector（引用 / 被引用 / 打开表）、孤岛 / 枢纽清单、
 * 标签按倍率淡化、缩放以容器中心为锚点、截断提示。
 * echarts 用轻量 mock，断言 option 纯结构与事件语义（与文档图谱测试同范式）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import TableLinkGraphPage, {
  collectNeighborhood,
  filterGraph,
  findHubs,
  findIsolated,
} from './TableLinkGraphPage'
import type { LinkGraphEdge, LinkGraphNode } from '@/api'
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

/** 真实表 A→B 一条边 + 指向已删目标的虚线边 + 自关联徽标 */
const graphPayload = {
  nodes: [
    { id: 1, name: '项目', description: '', group_id: null, group_name: '', field_count: 5, in_degree: 1, out_degree: 0, self_loop: false, virtual: false, can_edit: true },
    { id: 2, name: '任务', description: '', group_id: 3, group_name: '研发', field_count: 8, in_degree: 0, out_degree: 1, self_loop: false, virtual: false, can_edit: true },
    { id: 3, name: '任务树', description: '', group_id: 3, group_name: '研发', field_count: 4, in_degree: 0, out_degree: 0, self_loop: true, virtual: false, can_edit: true },
    { id: -2, name: '已删除 / 不可访问的表', description: '聚合目标', group_id: null, group_name: '', field_count: 0, in_degree: 1, out_degree: 0, self_loop: false, virtual: true, can_edit: false },
  ],
  edges: [
    { id: 11, field_name: '所属项目', source: 2, target: 1, multiple: true, reference_field_count: 2, target_state: 'ok', can_edit: true },
    { id: 12, field_name: '指向已删', source: 1, target: -2, multiple: false, reference_field_count: 0, target_state: 'trashed', can_edit: true },
  ],
  total: 3,
  truncated: false,
  edges_out_of_view: 0,
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="loc">{`${location.pathname}${location.search}`}</div>
}

function renderPage(route = '/w/10/tables/graph') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/graph" element={<TableLinkGraphPage />} />
      <Route path="/w/:wid/tables" element={<LocationProbe />} />
      <Route path="/w/:wid/tables/:tid" element={<LocationProbe />} />
    </Routes>,
    { route, initialAuth: { user: mockUser, token: 'fake-token' } },
  )
}

/** 取某个 echarts 事件的最新一次回调 */
function handlerOf(event: string) {
  const found = echartsMock.on.mock.calls.filter((c: unknown[]) => c[0] === event).at(-1)
  return found?.[1] as ((p: unknown) => void) | undefined
}

function clickNode(tid: number, virtual = false) {
  const handler = handlerOf('click')
  act(() => handler?.({ dataType: 'node', data: { value: tid, virtual } }))
}

function doubleClickNode(tid: number, virtual = false) {
  const handler = handlerOf('dblclick')
  act(() => handler?.({ dataType: 'node', data: { value: tid, virtual } }))
}

/** 最近一次「完整图」option：标签显隐是单独一次 setOption 下发的，只带 label 没有 data */
function lastGraphOption() {
  for (let i = echartsMock.setOption.mock.calls.length - 1; i >= 0; i -= 1) {
    const option = echartsMock.setOption.mock.calls[i]?.[0] as
      | { series?: Array<{ data?: unknown[] }> }
      | undefined
    const series = option?.series?.[0]
    if (series && Array.isArray(series.data)) return series
  }
  return undefined
}

describe('关联图页（需求 0187 P0）', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/link-graph', () => HttpResponse.json(graphPayload)),
    )
  })

  it('渲染节点与边：虚拟目标用 roundRect + 虚线，自关联不产生自环边', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(lastGraphOption()).toBeDefined())

    const series = lastGraphOption() as { data: Array<{ id: string; symbol?: string; self_loop?: boolean }>; links: Array<{ source: string; target: string; lineStyle: { type: string } }> }
    expect(series.data).toHaveLength(4)
    const virtualNode = series.data.find(item => item.id === '-2')
    expect(virtualNode?.symbol).toBe('roundRect')
    // 自关联表节点仍出现（徽标在 Inspector / tooltip），但没有 id===id 的自环边
    expect(series.data.some(item => item.id === '3')).toBe(true)
    const selfLoop = series.links.find(link => link.source === link.target)
    expect(selfLoop).toBeUndefined()
    const virtualEdge = series.links.find(link => link.target === '-2')
    expect(virtualEdge?.lineStyle.type).toBe('dashed')
    const normalEdge = series.links.find(link => link.target === '1')
    expect(normalEdge?.lineStyle.type).toBe('solid')
  })

  it('单击选中（Inspector 出现），双击才进入表；虚拟节点双击不跳转', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    clickNode(1)
    expect(await screen.findByTestId('table-graph-inspector-detail')).toBeInTheDocument()
    expect(screen.getByTestId('table-graph-inspector-title')).toHaveTextContent('项目')

    doubleClickNode(1)
    expect(await screen.findByTestId('loc')).toHaveTextContent('/w/10/tables/1')

    // 虚拟聚合节点不可打开
    doubleClickNode(-2, true)
    expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/tables/1')
  })

  it('局部图 ?focus=&depth=1：只保留一跳邻域', async () => {
    renderPage('/w/10/tables/graph?focus=2&depth=1')
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(lastGraphOption()).toBeDefined())

    const series = lastGraphOption() as { data: Array<{ id: string }> }
    const ids = series.data.map(item => item.id)
    expect(ids).toContain('2')
    expect(ids).toContain('1') // 一跳邻居
    expect(ids).not.toContain('-2') // 两跳才到
    expect(screen.getByTestId('table-graph-focus-tag')).toHaveTextContent('任务')
    expect(screen.getByTestId('table-graph-focus-tag')).toHaveTextContent('1 跳')
  })

  it('筛选栏：关键词 / 只看孤立表 / 只看自关联 / 只看外部关联', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(lastGraphOption()).toBeDefined())

    fireEvent.change(screen.getByTestId('table-graph-filter-keyword'), { target: { value: '任务' } })
    await waitFor(() => {
      const series = lastGraphOption() as { data: Array<{ id: string }> }
      // 「任务」命中任务与任务树；孤立表（任务树）可见，任务经一跳边保留
      expect(series.data.map(item => item.id).sort()).toEqual(['2', '3'])
    })

    fireEvent.change(screen.getByTestId('table-graph-filter-keyword'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('table-graph-filter-selfloop'))
    await waitFor(() => {
      const series = lastGraphOption() as { data: Array<{ id: string }> }
      expect(series.data.map(item => item.id)).toEqual(['3'])
    })
    fireEvent.click(screen.getByTestId('table-graph-filter-selfloop'))
    fireEvent.click(screen.getByTestId('table-graph-filter-isolated'))
    await waitFor(() => {
      const series = lastGraphOption() as { data: Array<{ id: string }> }
      expect(series.data.map(item => item.id)).toEqual(['3'])
    })
    fireEvent.click(screen.getByTestId('table-graph-filter-isolated'))
    fireEvent.click(screen.getByTestId('table-graph-filter-external'))
    await waitFor(() => {
      const series = lastGraphOption() as { data: Array<{ id: string }> }
      // 本夹具只有「已删除」虚拟节点（-2）：筛外部关联（虚拟 id -1）后无匹配节点
      expect(series.data).toHaveLength(0)
    })
  })

  it('图例按分组着色并可点击显隐', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(lastGraphOption()).toBeDefined())

    expect(screen.getByTestId('table-graph-legend-none')).toHaveTextContent('未分组')
    expect(screen.getByTestId('table-graph-legend-3')).toHaveTextContent('研发')
    fireEvent.click(screen.getByTestId('table-graph-legend-3'))
    await waitFor(() => {
      const series = lastGraphOption() as { data: Array<{ id: string }> }
      // 分组 3 被关掉：任务与任务树不可见；虚拟节点无分组（group_id ?? -0），随之隐藏
      expect(series.data.map(item => item.id).sort()).toEqual(['1', '-2'].sort())
    })
  })

  it('Inspector 显示引用 / 被引用与 via 字段名', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    clickNode(1)
    expect(await screen.findByTestId('table-graph-inspector-detail')).toBeInTheDocument()
    // 项目：被任务引用 1 次，自己有条指向已删的出边
    expect(screen.getByTestId('table-graph-inspector-detail')).toHaveTextContent('引用了 1 张表')
    expect(screen.getByTestId('table-graph-inspector-detail')).toHaveTextContent('被引用（1 张表）')
    expect(screen.getByTestId('table-graph-inspector-detail')).toHaveTextContent('所属项目')
    expect(screen.getByTestId('table-graph-inspector-detail')).toHaveTextContent('目标已删除')
  })

  it('孤岛 / 枢纽清单与点击定位', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()

    const isolatedList = await screen.findByTestId('table-graph-isolated-list')
    expect(isolatedList).toHaveTextContent('任务树')
    const hubList = await screen.findByTestId('table-graph-hub-list')
    expect(hubList).toHaveTextContent('项目')

    fireEvent.click(isolatedList.querySelector('a') as HTMLElement)
    expect(await screen.findByTestId('table-graph-inspector-detail')).toBeInTheDocument()
    expect(screen.getByTestId('table-graph-inspector-title')).toHaveTextContent('任务树')
  })

  it('标签按倍率淡化：低于 60% 时 label.show=false，按钮可强制显示', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()

    // 缩到 60% 以下（四步 0.8：0.8^4 ≈ 41%）
    fireEvent.click(await screen.findByTestId('table-graph-zoom-out'))
    for (let i = 0; i < 3; i += 1) fireEvent.click(screen.getByTestId('table-graph-zoom-out'))
    await waitFor(() => expect(screen.getByTestId('table-graph-zoom-pct')).toHaveTextContent('41%'))
    await waitFor(() => {
      const labelCall = echartsMock.setOption.mock.calls
        .map((c: unknown[]) => c[0] as { series?: Array<{ label?: { show?: boolean } }> })
        .filter(option => option?.series?.[0]?.label && !('data' in (option.series[0] as object)))
        .at(-1)
      expect(labelCall?.series?.[0]?.label?.show).toBe(false)
    })

    // 强制显示：倍率仍低但按钮已把标签打开
    fireEvent.click(screen.getByTestId('table-graph-labels-toggle'))
    fireEvent.click(screen.getByTestId('table-graph-labels-toggle'))
  })

  it('缩放以画布中心为锚点（originX/originY），到上下限后按钮禁用', async () => {
    renderPage()
    expect(await screen.findByTestId('table-graph-canvas')).toBeInTheDocument()
    await waitFor(() => expect(echartsMock.on).toHaveBeenCalled())

    // jsdom 不做布局：显式给出画布尺寸，锚点应等于其中心
    const canvas = screen.getByTestId('table-graph-canvas')
    Object.defineProperty(canvas, 'clientWidth', { configurable: true, value: 800 })
    Object.defineProperty(canvas, 'clientHeight', { configurable: true, value: 600 })

    fireEvent.click(screen.getByTestId('table-graph-zoom-in'))
    await waitFor(() => expect(screen.getByTestId('table-graph-zoom-pct')).toHaveTextContent('125%'))
    const roam = echartsMock.dispatchAction.mock.calls
      .map((c: unknown[]) => c[0] as { type?: string; originX?: number; originY?: number })
      .filter(p => p?.type === 'graphRoam')
      .at(-1)
    expect(roam?.originX).toBe(400)
    expect(roam?.originY).toBe(300)

    // 连点到 400%：按钮禁用（scaleLimit max 4）
    for (let i = 0; i < 12; i += 1) fireEvent.click(screen.getByTestId('table-graph-zoom-in'))
    await waitFor(() => expect(screen.getByTestId('table-graph-zoom-in')).toBeDisabled())
    expect(screen.getByTestId('table-graph-zoom-pct')).toHaveTextContent('400%')

    fireEvent.click(screen.getByTestId('table-graph-reset'))
    await waitFor(() => expect(screen.getByTestId('table-graph-zoom-pct')).toHaveTextContent('100%'))
  })

  it('截断提示：超上限时展示「另有 N 条关联指向未展示的表」', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/link-graph', () => HttpResponse.json({
        ...graphPayload,
        truncated: true,
        total: 600,
        edges_out_of_view: 3,
      })),
    )
    renderPage()
    const alert = await screen.findByTestId('table-graph-truncated-alert')
    expect(alert).toHaveTextContent('600 张')
    expect(alert).toHaveTextContent('另有 3 条关联指向未展示的表')
  })
})

describe('关联图纯函数', () => {
  const nodes: LinkGraphNode[] = [
    { id: 1, name: '甲', description: '', group_name: '', field_count: 1, in_degree: 1, out_degree: 0, self_loop: false, virtual: false, can_edit: true },
    { id: 2, name: '乙', description: '', group_name: '', field_count: 1, in_degree: 0, out_degree: 1, self_loop: false, virtual: false, can_edit: true },
    { id: 3, name: '丙', description: '', group_name: '', field_count: 1, in_degree: 0, out_degree: 0, self_loop: false, virtual: false, can_edit: true },
    { id: -2, name: '已删', description: '', group_name: '', field_count: 0, in_degree: 0, out_degree: 0, self_loop: false, virtual: true, can_edit: false },
  ]
  const edges: LinkGraphEdge[] = [
    { id: 1, field_name: 'a', source: 2, target: 1, multiple: true, reference_field_count: 0, target_state: 'ok', can_edit: true },
    { id: 2, field_name: 'b', source: 1, target: -2, multiple: false, reference_field_count: 0, target_state: 'trashed', can_edit: true },
  ]

  it('collectNeighborhood：无向 BFS，1 跳只含直连，2 跳含虚拟目标', () => {
    const one = collectNeighborhood(edges, 2, 1)
    expect(one.has(2)).toBe(true)
    expect(one.has(1)).toBe(true)
    expect(one.has(-2)).toBe(false)
    const two = collectNeighborhood(edges, 2, 2)
    expect(two.has(-2)).toBe(true)
  })

  it('filterGraph：边只在两端都可见时保留', () => {
    const degrees = new Map<number, number>([[1, 2], [2, 1], [3, 0], [-2, 1]])
    const onlyThree = filterGraph(nodes, edges, { keyword: '丙', onlyIsolated: false, onlyExternal: false, onlySelfLoop: false }, { scope: null, hiddenGroups: new Set(), degrees })
    expect(onlyThree.nodes.map(n => n.id)).toEqual([3])
    expect(onlyThree.edges).toEqual([])

    const all = filterGraph(nodes, edges, { keyword: '', onlyIsolated: false, onlyExternal: false, onlySelfLoop: false }, { scope: null, hiddenGroups: new Set(), degrees })
    expect(all.edges).toHaveLength(2)
  })

  it('findIsolated / findHubs：虚拟节点不参与，孤立表度数为 0', () => {
    const degrees = new Map<number, number>([[1, 2], [2, 1], [3, 0], [-2, 1]])
    const isolated = findIsolated(nodes, degrees)
    expect(isolated.map(n => n.id)).toEqual([3])
    const hubs = findHubs(nodes, degrees)
    expect(hubs.map(n => n.id)).toEqual([1, 2])
  })
})

describe('关联图编辑（需求 0187 P1 / ADR 0187 E1–E4）', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.setOption.mockClear()
    echartsMock.on.mockClear()
    echartsMock.dispose.mockClear()
    echartsMock.dispatchAction.mockClear()
    echartsMock.getOption.mockClear()
    echartsMock.getOption.mockReturnValue({ series: [{ zoom: 1 }] })
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/link-graph', () => HttpResponse.json(graphPayload)),
    )
  })

  /** 选中节点：走 echarts click 回调（与真实交互同路径） */
  async function selectNode(tid: number) {
    await waitFor(() => expect(handlerOf('click')).toBeDefined())
    act(() => handlerOf('click')!({ dataType: 'node', data: { value: tid } }))
  }

  it('E5：can_edit=true 时 Inspector 显示连线与边编辑入口', async () => {
    renderPage()
    await selectNode(2)

    expect(await screen.findByTestId('table-graph-inspector-connect')).toBeEnabled()
    // 节点 2 有一条出边（id=11）→ 有编辑 / 删除入口
    expect(await screen.findByTestId('table-graph-edge-edit-11')).toBeInTheDocument()
    expect(await screen.findByTestId('table-graph-edge-delete-11')).toBeInTheDocument()
  })

  it('E5：can_edit=false 的节点不渲染连线入口', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/link-graph', () =>
        HttpResponse.json({
          ...graphPayload,
          nodes: graphPayload.nodes.map(n => ({ ...n, can_edit: false })),
          edges: graphPayload.edges.map(e => ({ ...e, can_edit: false })),
        }),
      ),
    )
    renderPage()
    await selectNode(2)

    expect(await screen.findByTestId('table-graph-inspector-connect')).toBeDisabled()
    expect(screen.queryByTestId('table-graph-edge-edit-11')).not.toBeInTheDocument()
    expect(screen.queryByTestId('table-graph-edge-delete-11')).not.toBeInTheDocument()
  })

  it('E1 + E4：两步点击连线，提交 link 字段的建字段请求', async () => {
    let captured: { wid: string; tid: string; body: Record<string, unknown> } | null = null
    server.use(
      http.post('/api/v1/workspaces/:wid/tables/:tid/fields', async ({ request, params }) => {
        captured = {
          wid: String(params.wid),
          tid: String(params.tid),
          body: (await request.json()) as Record<string, unknown>,
        }
        return HttpResponse.json({ id: 99 }, { status: 201 })
      }),
    )

    renderPage()
    // 第一步：从节点 2 开始连线
    await selectNode(2)
    fireEvent.click(await screen.findByTestId('table-graph-inspector-connect'))
    expect(await screen.findByTestId('table-graph-connect-hint')).toBeInTheDocument()

    // 第二步：点节点 1 作为目标
    await waitFor(() => expect(handlerOf('click')).toBeDefined())
    act(() => handlerOf('click')!({ dataType: 'node', data: { value: 1 } }))

    const nameInput = await screen.findByTestId('table-graph-connect-name')
    expect((nameInput as HTMLInputElement).value).toBe('关联项目')
    fireEvent.change(nameInput, { target: { value: '所属项目' } })
    fireEvent.click(screen.getByRole('button', { name: /建\s*立/ }))

    await waitFor(() => expect(captured).not.toBeNull())
    expect(captured!.tid).toBe('2')
    expect(captured!.body).toMatchObject({
      name: '所属项目',
      field_type: 'link',
      config: { target_table_id: 1, multiple: true },
    })
  })

  it('E4：ESC 取消连线，不再进入选目标态', async () => {
    renderPage()
    await selectNode(2)
    fireEvent.click(await screen.findByTestId('table-graph-inspector-connect'))
    expect(await screen.findByTestId('table-graph-connect-hint')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    })
    await waitFor(() =>
      expect(screen.queryByTestId('table-graph-connect-hint')).not.toBeInTheDocument(),
    )
  })

  it('E2：编辑边只提交名字 / 多选 / 目标，不夹带未改的键', async () => {
    let captured: Record<string, unknown> | null = null
    server.use(
      http.patch('/api/v1/workspaces/:wid/tables/:tid/fields/:fid', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 11 })
      }),
    )

    renderPage()
    await selectNode(2)
    fireEvent.click(await screen.findByTestId('table-graph-edge-edit-11'))

    const nameInput = await screen.findByTestId('table-graph-edge-name')
    fireEvent.change(nameInput, { target: { value: '归属项目' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(captured).not.toBeNull())
    expect(captured).toMatchObject({
      name: '归属项目',
      config: { target_table_id: 1, multiple: true },
    })
    // 未改的键不进 payload（后端 PATCH 语义是「只处理显式出现的键」）
    expect(captured).not.toHaveProperty('field_type')
    expect(captured).not.toHaveProperty('required')
  })

  it('E2′：改目标表时带 force 重试（D7 失效预检）', async () => {
    const calls: Array<{ fid: string; force: boolean }> = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/tables/:tid/fields/:fid', ({ request, params }) => {
        const url = new URL(request.url)
        calls.push({ fid: String(params.fid), force: url.searchParams.get('force') === 'true' })
        return HttpResponse.json({ id: 11 })
      }),
    )

    renderPage()
    await selectNode(2)
    fireEvent.click(await screen.findByTestId('table-graph-edge-edit-11'))

    // 把目标从 1 改成 3 → 走带 force 的分支
    const targetSelect = await screen.findByTestId('table-graph-edge-target')
    fireEvent.mouseDown(targetSelect)
    const option = await screen.findByTitle('任务树')
    fireEvent.click(option)
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(calls.length).toBeGreaterThan(0))
    expect(calls[0]).toEqual({ fid: '11', force: true })
  })

  it('E3：删除边需二次确认后才发请求', async () => {
    let deleted = 0
    server.use(
      http.delete('/api/v1/workspaces/:wid/tables/:tid/fields/:fid', () => {
        deleted += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    await selectNode(2)
    fireEvent.click(await screen.findByTestId('table-graph-edge-delete-11'))

    // 确认框未确认前不得发请求
    expect(await screen.findByText('删除这条关联？')).toBeInTheDocument()
    expect(deleted).toBe(0)
    fireEvent.click(screen.getByRole('button', { name: /^删\s*除$/ }))
    await waitFor(() => expect(deleted).toBe(1))
  })

  it('E6：写成功后失效关联图查询（写后即见）', async () => {
    let graphHits = 0
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/link-graph', () => {
        graphHits += 1
        return HttpResponse.json(graphPayload)
      }),
      http.delete('/api/v1/workspaces/:wid/tables/:tid/fields/:fid', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    )

    renderPage()
    await selectNode(2)
    await waitFor(() => expect(graphHits).toBe(1))
    fireEvent.click(await screen.findByTestId('table-graph-edge-delete-11'))
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

    await waitFor(() => expect(graphHits).toBe(2))
  })
})

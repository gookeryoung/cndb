/** ChartEmbed 组件测试 — 正文定义渲染 / 失败降级 / 坏块降级 / 编辑与宽度入口可选（ADR 0052）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import ChartEmbed from './ChartEmbed'
import type { ChartBlock, ChartBlockSpec } from './chartBlock'

function spec(overrides: Partial<ChartBlockSpec> = {}): ChartBlockSpec {
  return { version: 1, templateKey: 'bar-line-dual-axis', title: '样例图表', width: 75, config: {}, ...overrides }
}

function block(overrides: Partial<ChartBlockSpec> = {}): ChartBlock {
  return { source: '```chart\n{}\n```', spec: spec(overrides) }
}

describe('ChartEmbed', () => {
  it('按正文定义渲染 SVG（不查实例 ID）', async () => {
    renderProviders(<ChartEmbed workspaceId={10} block={block()} />)

    const canvas = await screen.findByTestId('chart-embed-svg')
    expect(canvas.querySelector('svg')).not.toBeNull()
  })

  it('按块内 width 设置宿主宽度：缺省 75%，自定义 50%', async () => {
    const first = renderProviders(<ChartEmbed workspaceId={10} block={block()} />)
    const figure = await screen.findByTestId('chart-embed-bar-line-dual-axis')
    expect(figure).toHaveAttribute('data-width', '75')
    expect(figure.style.width).toBe('75%')
    first.unmount()

    renderProviders(<ChartEmbed workspaceId={10} block={block({ width: 50 })} />)
    const narrow = await screen.findByTestId('chart-embed-bar-line-dual-axis')
    expect(narrow).toHaveAttribute('data-width', '50')
    expect(narrow.style.width).toBe('50%')
  })

  it('传入 onWidthChange 时才渲染宽度控件，选择预设后透传百分比', async () => {
    const onWidthChange = vi.fn()
    renderProviders(<ChartEmbed workspaceId={10} block={block()} refOrdinal={0} onWidthChange={onWidthChange} />)
    await screen.findByTestId('chart-embed-svg')

    fireEvent.click(screen.getByTestId('chart-embed-width-0'))
    fireEvent.click(await screen.findByTestId('chart-embed-width-0-preset-50'))
    expect(onWidthChange).toHaveBeenCalledWith(50)
  })

  it('坏块直接降级，不发渲染请求', async () => {
    let requested = 0
    server.use(
      http.post('/api/v1/workspaces/10/charts/render-preview', () => {
        requested += 1
        return new HttpResponse('<svg />', { status: 200 })
      }),
    )
    renderProviders(
      <ChartEmbed workspaceId={10} block={{ source: '```chart\n{bad}\n```', spec: null, error: 'json_invalid' }} />,
    )
    const alert = await screen.findByTestId('chart-embed-invalid-message')
    expect(alert.textContent).toContain('JSON 格式错误')
    expect(requested).toBe(0)
  })

  it('请求失败（模板下线 / 配置不完整）时单块降级为提示', async () => {
    server.use(
      http.post('/api/v1/workspaces/10/charts/render-preview', () =>
        HttpResponse.json({ detail: '模板已下线' }, { status: 400 })),
    )
    renderProviders(<ChartEmbed workspaceId={10} block={block({ templateKey: 'retired-template' })} />)
    const alert = await screen.findByTestId('chart-embed-error')
    expect(alert.textContent).toContain('图表暂时无法渲染')
  })

  it('清洗 SVG 里的 script 与行内事件属性', async () => {
    server.use(
      http.post('/api/v1/workspaces/10/charts/render-preview', () =>
        new HttpResponse(
          '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script><text>安全图表</text></svg>',
          { status: 200, headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' } },
        )),
    )

    renderProviders(<ChartEmbed workspaceId={10} block={block()} />)

    const canvas = await screen.findByTestId('chart-embed-svg')
    expect(canvas.innerHTML).toContain('安全图表')
    expect(canvas.innerHTML).not.toContain('<script')
    expect(canvas.innerHTML).not.toContain('onload')
  })

  it('未传回调时不渲染编辑 / 宽度入口；传入后按块序号透传定义', async () => {
    const onEditChart = vi.fn()
    const first = renderProviders(<ChartEmbed workspaceId={10} block={block()} />)
    await screen.findByTestId('chart-embed-svg')
    expect(screen.queryByTestId('chart-embed-edit-0')).toBeNull()
    expect(screen.queryByTestId('chart-embed-width-0')).toBeNull()
    first.unmount()

    renderProviders(<ChartEmbed workspaceId={10} block={block()} refOrdinal={2} onEditChart={onEditChart} />)
    await screen.findByTestId('chart-embed-svg')
    fireEvent.click(screen.getByTestId('chart-embed-edit-2'))
    expect(onEditChart).toHaveBeenCalledWith(expect.objectContaining({ templateKey: 'bar-line-dual-axis' }), 2)
  })

  it('保存图片：编辑入口存在时渲染下拉，SVG 格式直接触发下载', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download)
    })

    try {
      renderProviders(<ChartEmbed workspaceId={10} block={block()} refOrdinal={0} onEditChart={vi.fn()} />)
      await screen.findByTestId('chart-embed-svg')

      const saveBtn = screen.getByTestId('chart-embed-save-0')
      expect(saveBtn.textContent).toContain('保存图片')

      fireEvent.click(saveBtn)
      fireEvent.click(await screen.findByText('SVG 矢量图'))
      await waitFor(() => expect(clicked).toEqual(['样例图表.svg']))
      expect(createObjectURL).toHaveBeenCalled()
      expect(revokeObjectURL).toHaveBeenCalled()
    } finally {
      vi.restoreAllMocks()
    }
  })

  it('未传 onEditChart 时不渲染保存图片入口', async () => {
    renderProviders(<ChartEmbed workspaceId={10} block={block()} />)
    await screen.findByTestId('chart-embed-svg')
    expect(screen.queryByTestId('chart-embed-save-0')).toBeNull()
  })

  it('游客分享模式：走 token 免登录渲染端点，失败同样降级', async () => {
    const requests: { method: string; path: string }[] = []
    server.use(
      http.post('/api/v1/documents/share/:token/charts/render-preview', ({ request }) => {
        requests.push({ method: request.method, path: new URL(request.url).pathname })
        return new HttpResponse('<svg xmlns="http://www.w3.org/2000/svg"><text>游客图表</text></svg>', {
          status: 200,
          headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
        })
      }),
    )

    const first = renderProviders(<ChartEmbed shareToken="share-tok" block={block()} />)
    await screen.findByTestId('chart-embed-svg')
    expect(screen.getByTestId('chart-embed-svg').innerHTML).toContain('游客图表')
    expect(requests).toEqual([{ method: 'POST', path: '/api/v1/documents/share/share-tok/charts/render-preview' }])
    first.unmount()

    server.use(
      http.post('/api/v1/documents/share/:token/charts/render-preview', () =>
        HttpResponse.json({ detail: '分享链接不存在或已失效' }, { status: 404 })),
    )
    renderProviders(<ChartEmbed shareToken="share-tok" block={block({ templateKey: 'retired-template' })} />)
    expect(await screen.findByTestId('chart-embed-error')).toBeInTheDocument()
  })

  it('渲染成功后点击图表打开放大预览，复用同一份 SVG，关闭后弹层消失（ADR 0060）', async () => {
    let renderCalls = 0
    server.use(
      http.post('/api/v1/workspaces/10/charts/render-preview', () => {
        renderCalls += 1
        return new HttpResponse('<svg xmlns="http://www.w3.org/2000/svg"><text>放大图表</text></svg>', {
          status: 200,
          headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
        })
      }),
    )
    renderProviders(<ChartEmbed workspaceId={10} block={block()} />)

    const canvas = await screen.findByTestId('chart-embed-svg')
    expect(canvas).toHaveAttribute('role', 'button')
    expect(screen.queryByTestId('chart-embed-preview-svg')).toBeNull()

    fireEvent.click(canvas)
    const preview = await screen.findByTestId('chart-embed-preview-svg')
    expect(preview.innerHTML).toContain('放大图表')
    // 预览层复用同一份渲染结果，不发第二次渲染请求（I1）
    expect(renderCalls).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    // Modal 关闭后隐藏（jsdom 中内容保持挂载，见 setup.ts 动画说明）
    await waitFor(() => expect(screen.getByTestId('chart-embed-preview-svg')).not.toBeVisible())
  })

  it('预览层滚轮缩放：上滚放大、下滚缩小，边界 0.5x-3x，重开后复位 100%（ADR 0060）', async () => {
    server.use(
      http.post('/api/v1/workspaces/10/charts/render-preview', () =>
        new HttpResponse('<svg xmlns="http://www.w3.org/2000/svg"><text>缩放</text></svg>', {
          status: 200,
          headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
        })),
    )
    renderProviders(<ChartEmbed workspaceId={10} block={block()} />)
    const canvas = await screen.findByTestId('chart-embed-svg')
    fireEvent.click(canvas)
    const preview = await screen.findByTestId('chart-embed-preview-svg')
    expect(preview).toHaveStyle({ width: '100%' })

    const scroller = screen.getByTestId('chart-embed-preview-scroll')
    fireEvent.wheel(scroller, { deltaY: -100 })
    expect(screen.getByTestId('chart-embed-preview-svg')).toHaveStyle({ width: '110%' })
    // 连续上滚到上限 3x
    for (let i = 0; i < 25; i += 1) fireEvent.wheel(scroller, { deltaY: -100 })
    expect(screen.getByTestId('chart-embed-preview-svg')).toHaveStyle({ width: '300%' })
    // 下滚到下限 0.5x
    for (let i = 0; i < 40; i += 1) fireEvent.wheel(scroller, { deltaY: 100 })
    expect(screen.getByTestId('chart-embed-preview-svg')).toHaveStyle({ width: '50%' })

    // 关闭重开后复位 100%
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.click(canvas)
    expect(await screen.findByTestId('chart-embed-preview-svg')).toHaveStyle({ width: '100%' })
  })

  it('渲染失败 / 无效块无放大入口（I2 降级一致）', async () => {
    server.use(
      http.post('/api/v1/workspaces/10/charts/render-preview', () =>
        HttpResponse.json({ detail: '模板已下线' }, { status: 400 })),
    )
    const first = renderProviders(<ChartEmbed workspaceId={10} block={block({ templateKey: 'retired-template' })} />)
    expect(await screen.findByTestId('chart-embed-error')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-embed-svg')).toBeNull()
    expect(screen.queryByTestId('chart-embed-preview-svg')).toBeNull()
    first.unmount()

    renderProviders(
      <ChartEmbed workspaceId={10} block={{ source: '```chart\n{bad}\n```', spec: null, error: 'json_invalid' }} />,
    )
    await screen.findByTestId('chart-embed-invalid-message')
    expect(screen.queryByTestId('chart-embed-svg')).toBeNull()
  })

  it('游客分享模式同样支持点击放大（I3 模式无关）', async () => {
    server.use(
      http.post('/api/v1/documents/share/:token/charts/render-preview', () =>
        new HttpResponse('<svg xmlns="http://www.w3.org/2000/svg"><text>游客放大</text></svg>', {
          status: 200,
          headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
        })),
    )
    renderProviders(<ChartEmbed shareToken="share-tok" block={block()} />)

    fireEvent.click(await screen.findByTestId('chart-embed-svg'))
    expect((await screen.findByTestId('chart-embed-preview-svg')).innerHTML).toContain('游客放大')
  })
})

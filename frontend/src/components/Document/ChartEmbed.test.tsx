/** ChartEmbed 组件测试 — 成功内联渲染 / 失败降级 / ETag 304 复用 / 编辑入口可选（ADR 0048 D7 / D10）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import ChartEmbed from './ChartEmbed'

describe('ChartEmbed', () => {
  it('成功拉取 SVG 并内联渲染', async () => {
    renderProviders(<ChartEmbed workspaceId={10} chartId={300} />)

    const canvas = await screen.findByTestId('chart-embed-svg-300')
    expect(canvas.querySelector('svg')).not.toBeNull()
  })

  it('按 width 设置宿主宽度：缺省 75%，自定义 50%', async () => {
    const first = renderProviders(<ChartEmbed workspaceId={10} chartId={300} />)
    const figure = await screen.findByTestId('chart-embed-300')
    expect(figure).toHaveAttribute('data-width', '75')
    expect(figure.style.width).toBe('75%')
    first.unmount()

    renderProviders(<ChartEmbed workspaceId={10} chartId={300} width={50} />)
    const narrow = await screen.findByTestId('chart-embed-300')
    expect(narrow).toHaveAttribute('data-width', '50')
    expect(narrow.style.width).toBe('50%')
  })

  it('传入 onWidthChange 时才渲染宽度控件，选择预设后透传百分比', async () => {
    const onWidthChange = vi.fn()
    renderProviders(<ChartEmbed workspaceId={10} chartId={300} onWidthChange={onWidthChange} />)
    await screen.findByTestId('chart-embed-svg-300')

    fireEvent.click(screen.getByTestId('chart-embed-width-300-0'))
    fireEvent.click(await screen.findByTestId('chart-embed-width-300-0-preset-50'))
    expect(onWidthChange).toHaveBeenCalledWith(50)
  })

  it('实例不存在 / 无权限时降级为占位提示（D7：单段降级不阻断）', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/charts/404', () =>
        HttpResponse.json({ detail: '图表不存在' }, { status: 404 })),
      // ChartEmbed 直接请求 render 端点（不先取实例详情），须一并覆盖
      http.get('/api/v1/workspaces/10/charts/404/render', () =>
        HttpResponse.json({ detail: '图表不存在' }, { status: 404 })),
    )

    renderProviders(<ChartEmbed workspaceId={10} chartId={404} />)

    const alert = await screen.findByTestId('chart-embed-404')
    // figure 先以骨架屏出现，Alert 在请求失败后才渲染
    await waitFor(() => expect(alert.textContent).toContain('图表引用无效'))
    expect(alert.textContent).toContain('#404')
  })

  it('清洗 SVG 里的 script 与行内事件属性', async () => {
    server.use(
      http.get('/api/v1/workspaces/10/charts/301/render', () =>
        new HttpResponse(
          '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script><text>安全图表</text></svg>',
          { status: 200, headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' } },
        )),
    )

    renderProviders(<ChartEmbed workspaceId={10} chartId={301} />)

    const canvas = await screen.findByTestId('chart-embed-svg-301')
    expect(canvas.innerHTML).toContain('安全图表')
    expect(canvas.innerHTML).not.toContain('<script')
    expect(canvas.innerHTML).not.toContain('onload')
  })

  it('ETag 命中 304 时复用上次产物（D10：不重复传输）', async () => {
    let requestCount = 0
    const etag = '"chart-embed-etag-test"'
    server.use(
      http.get('/api/v1/workspaces/10/charts/302/render', ({ request }) => {
        requestCount++
        if (request.headers.get('If-None-Match') === etag) {
          return new HttpResponse(null, { status: 304, headers: { ETag: etag } })
        }
        return new HttpResponse(
          '<svg xmlns="http://www.w3.org/2000/svg"><text>缓存图表</text></svg>',
          { status: 200, headers: { 'Content-Type': 'image/svg+xml; charset=utf-8', ETag: etag } },
        )
      }),
    )

    const first = renderProviders(<ChartEmbed workspaceId={10} chartId={302} />)
    expect(await screen.findByTestId('chart-embed-svg-302')).toBeInTheDocument()
    first.unmount()

    renderProviders(<ChartEmbed workspaceId={10} chartId={302} />)
    expect(await screen.findByTestId('chart-embed-svg-302')).toBeInTheDocument()
    expect(screen.getByTestId('chart-embed-svg-302').innerHTML).toContain('缓存图表')
    await waitFor(() => expect(requestCount).toBe(2))
  })

  it('未传 onEditChart 时不渲染编辑入口；传入后点击透传 chartId', async () => {
    const onEditChart = vi.fn()
    const first = renderProviders(<ChartEmbed workspaceId={10} chartId={300} />)
    await screen.findByTestId('chart-embed-svg-300')
    expect(screen.queryByTestId('chart-embed-edit-300')).toBeNull()
    expect(screen.queryByTestId('chart-embed-width-300-0')).toBeNull()
    first.unmount()

    renderProviders(<ChartEmbed workspaceId={10} chartId={300} onEditChart={onEditChart} />)
    await screen.findByTestId('chart-embed-svg-300')
    fireEvent.click(screen.getByTestId('chart-embed-edit-300'))
    expect(onEditChart).toHaveBeenCalledWith(300)
  })

  it('游客分享模式：走免登录匿名渲染端点（D9），失败同样降级', async () => {
    const requests: string[] = []
    server.use(
      http.get('/api/v1/documents/share/:token/charts/:cid/render', ({ request }) => {
        requests.push(new URL(request.url).pathname)
        return new HttpResponse('<svg xmlns="http://www.w3.org/2000/svg"><text>游客图表</text></svg>', {
          status: 200,
          headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' },
        })
      }),
    )

    const first = renderProviders(<ChartEmbed shareToken="share-tok" chartId={303} />)
    await screen.findByTestId('chart-embed-svg-303')
    expect(screen.getByTestId('chart-embed-svg-303').innerHTML).toContain('游客图表')
    expect(requests).toEqual(['/api/v1/documents/share/share-tok/charts/303/render'])
    first.unmount()

    server.use(
      http.get('/api/v1/documents/share/:token/charts/:cid/render', () =>
        HttpResponse.json({ detail: '分享链接不存在或已失效' }, { status: 404 })),
    )
    renderProviders(<ChartEmbed shareToken="share-tok" chartId={305} />)
    const alert = await screen.findByTestId('chart-embed-305')
    await waitFor(() => expect(alert.textContent).toContain('图表引用无效'))
  })
})

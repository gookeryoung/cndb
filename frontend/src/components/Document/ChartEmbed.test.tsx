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
    first.unmount()

    renderProviders(<ChartEmbed workspaceId={10} chartId={300} onEditChart={onEditChart} />)
    await screen.findByTestId('chart-embed-svg-300')
    fireEvent.click(screen.getByTestId('chart-embed-edit-300'))
    expect(onEditChart).toHaveBeenCalledWith(300)
  })
})

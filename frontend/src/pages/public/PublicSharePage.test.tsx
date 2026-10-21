/** 公开分享页（ADR 0017）——加载 / 密码 / 失效三态与免登录只读渲染. */

import { describe, expect, it, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes, useLocation } from 'react-router-dom'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import PublicSharePage from './PublicSharePage'

const TOKEN = 'share-token'

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="share-location">{loc.pathname}</div>
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route
        path="/public/share/:token"
        element={
          <>
            <PublicSharePage />
            <LocationProbe />
          </>
        }
      />
    </Routes>,
    { route: `/public/share/${TOKEN}` },
  )
}

const META = '/api/v1/documents/share/:token/meta'
const CONTENT = '/api/v1/documents/share/:token'

describe('PublicSharePage', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('无密码分享：渲染标题与只读正文，停留在公开页', async () => {
    server.use(
      http.get(META, () => HttpResponse.json({ title: '公开文档', has_password: false })),
      http.get(CONTENT, () =>
        HttpResponse.json({
          title: '公开文档',
          updated_at: '2026-10-21T10:00:00Z',
          content: '# 公开标题\n\n任何人都能看到的正文。\n',
        })),
    )

    renderPage()

    expect(await screen.findByText('公开标题')).toBeInTheDocument()
    expect(screen.getByText('任何人都能看到的正文。')).toBeInTheDocument()
    expect(screen.getByTestId('share-location')).toHaveTextContent(`/public/share/${TOKEN}`)
    expect(screen.getByText('只读分享')).toBeInTheDocument()
  })

  it('meta 404：显示统一的「链接不存在或已失效」', async () => {
    server.use(http.get(META, () => new HttpResponse(null, { status: 404 })))

    renderPage()

    expect(await screen.findByTestId('public-share-gone')).toHaveTextContent('链接不存在或已失效')
  })

  it('meta 非 404 失败：显示加载失败并提供重试语义', async () => {
    server.use(http.get(META, () => new HttpResponse(null, { status: 500 })))

    renderPage()

    expect(await screen.findByText('分享加载失败')).toBeInTheDocument()
  })

  it('密码分享：先展示密码框，正确密码后才渲染正文', async () => {
    let contentHits = 0
    const submitted: string[] = []
    server.use(
      http.get(META, () => HttpResponse.json({ title: '加密文档', has_password: true })),
      http.get(CONTENT, () => {
        contentHits += 1
        return HttpResponse.json({ title: '加密文档', updated_at: '2026-10-21T10:00:00Z' })
      }),
      http.post(CONTENT, async ({ request }) => {
        const body = (await request.json()) as { password?: string }
        submitted.push(body.password ?? '')
        if (body.password !== 'open-sesame') {
          return new HttpResponse(null, { status: 403 })
        }
        return HttpResponse.json({
          title: '加密文档',
          updated_at: '2026-10-21T10:00:00Z',
          content: '密码正确后的正文。',
        })
      }),
    )

    renderPage()

    const input = await screen.findByTestId('public-share-password')
    // 需要密码时不应提前请求正文
    expect(contentHits).toBe(0)

    fireEvent.change(input, { target: { value: 'wrong' } })
    fireEvent.click(screen.getByTestId('public-share-unlock'))
    expect(await screen.findByTestId('public-share-password-error')).toHaveTextContent('密码错误')

    fireEvent.change(input, { target: { value: 'open-sesame' } })
    fireEvent.click(screen.getByTestId('public-share-unlock'))

    expect(await screen.findByText('密码正确后的正文。')).toBeInTheDocument()
    expect(submitted).toEqual(['wrong', 'open-sesame'])
  })

  it('正文接口在 meta 之后失效：仍按 404 展示已失效', async () => {
    server.use(
      http.get(META, () => HttpResponse.json({ title: '公开文档', has_password: false })),
      http.get(CONTENT, () => new HttpResponse(null, { status: 404 })),
    )

    renderPage()

    expect(await screen.findByText('链接不存在或已失效')).toBeInTheDocument()
  })

  it('正文接口其它失败：展示加载失败', async () => {
    server.use(
      http.get(META, () => HttpResponse.json({ title: '公开文档', has_password: false })),
      http.get(CONTENT, () => new HttpResponse(null, { status: 500 })),
    )

    renderPage()

    expect(await screen.findByText('分享加载失败')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('public-share-loading')).toBeNull())
  })

  it('缺少 token：直接展示失效结果', () => {
    renderProviders(<PublicSharePage />)

    expect(screen.getByText('链接不存在或已失效')).toBeInTheDocument()
  })
})

/** DocumentImage 组件测试 —— 站内引用鉴权渲染 / 外部 URL 直出 / 失败兜底. */

import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import DocumentImage from './DocumentImage'

describe('DocumentImage', () => {
  it('站内 file: 引用：带鉴权取 blob 后渲染 object URL', async () => {
    let requested = ''
    server.use(
      http.get('/api/v1/workspaces/10/files/:fileKey', ({ request, params }) => {
        requested = String(params.fileKey) + new URL(request.url).search
        return new HttpResponse(new Uint8Array([137, 80, 78, 71]), {
          status: 200,
          headers: { 'Content-Type': 'image/png' },
        })
      }),
    )

    renderProviders(<DocumentImage workspaceId={10} src="file:abc.png" alt="架构图" />)

    // antd Image 会包一层容器，testid 落在容器上，真正的 img 在其中
    const container = await screen.findByTestId('doc-image-inline')
    const img = (container.tagName === 'IMG' ? container : container.querySelector('img')) as HTMLImageElement
    await waitFor(() => expect(img?.getAttribute('src')).toMatch(/^blob:/))
    expect(img).toHaveAttribute('alt', '架构图')
    expect(requested).toBe('abc.png?inline=true')
  })

  it('外部 URL 直接渲染，不发文件请求', async () => {
    let hits = 0
    server.use(
      http.get('/api/v1/workspaces/10/files/:fileKey', () => {
        hits += 1
        return new HttpResponse(null, { status: 404 })
      }),
    )

    renderProviders(<DocumentImage workspaceId={10} src="https://example.com/a.png" alt="外链" />)

    const img = await screen.findByTestId('doc-image-external')
    expect(img).toHaveAttribute('src', 'https://example.com/a.png')
    expect(hits).toBe(0)
  })

  it('取文件失败时展示可读提示（含 file_key）', async () => {
    server.use(http.get('/api/v1/workspaces/10/files/:fileKey', () => new HttpResponse(null, { status: 500 })))

    renderProviders(<DocumentImage workspaceId={10} src="file:broken.png" />)

    const tip = await screen.findByTestId('doc-image-missing')
    expect(tip).toHaveTextContent('broken.png')
  })

  it('缺少工作区上下文时提示失败而不是空白', async () => {
    renderProviders(<DocumentImage src="file:abc.png" />)
    expect(await screen.findByTestId('doc-image-missing')).toBeInTheDocument()
  })

  it('公开分享模式：站内图片直接拼免登录 URL，不请求工作区附件接口', async () => {
    let hits = 0
    server.use(
      http.get('/api/v1/workspaces/:wid/files/:fileKey', () => {
        hits += 1
        return new HttpResponse(null, { status: 404 })
      }),
    )

    renderProviders(
      <DocumentImage workspaceId={10} publicFileBase="/api/v1/documents/share/tok/files" src="file:abc.png" alt="公开图" />,
    )

    const container = await screen.findByTestId('doc-image-public')
    const img = (container.tagName === 'IMG' ? container : container.querySelector('img')) as HTMLImageElement
    expect(img?.getAttribute('src')).toBe('/api/v1/documents/share/tok/files/abc.png')
    expect(img).toHaveAttribute('alt', '公开图')
    expect(hits).toBe(0)
  })

  it('公开分享模式：外部图片禁用 Referer，避免 token 经第三方泄露', async () => {
    renderProviders(
      <DocumentImage publicFileBase="/api/v1/documents/share/tok/files" src="https://example.com/a.png" alt="外链" />,
    )

    const img = await screen.findByTestId('doc-image-external')
    expect(img).toHaveAttribute('referrerpolicy', 'no-referrer')
  })
})

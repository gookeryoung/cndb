/** 原件族阅读器测试（ADR 0025 / 0087）：PDF / 图片 / Office / 预览失败态. */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import DocumentAssetView, { assetSuffix } from './DocumentAssetView'
import { renderProviders } from '@/test/render-providers'
import { documentsApi, type DocumentItem } from '@/api/documents'

// PPTX 渲染库体积大，单测只验证挂载分派；真实渲染由 PptxPreview.test.tsx 覆盖
vi.mock('./PptxPreview', () => ({
  default: ({ title }: { title: string }) => <div data-testid="pptx-preview-stub">{title}</div>,
}))
vi.mock('./PptxSlideshow', () => ({
  default: ({ title, onClose }: { title: string; onClose: () => void }) => (
    <div data-testid="pptx-slideshow-stub">
      {title}
      <button type="button" onClick={onClose}>退出放映</button>
    </div>
  ),
}))

const PDF_DOC: DocumentItem = {
  id: 31,
  workspace_id: 7,
  parent_id: null,
  title: '季度报告',
  slug: null,
  content_type: 'pdf',
  asset_mime: 'application/pdf',
  author: '',
  summary: '',
  toc_json: [],
  status: 'draft',
  is_folder: false,
  sort_order: 0,
  content_size: 2048,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-02T00:00:00Z',
  created_by_id: 1,
  updated_by_id: 1,
  tag_ids: [],
  version_count: 1,
  pinned: false,
}

function docOf(patch: Partial<DocumentItem>): DocumentItem {
  return { ...PDF_DOC, ...patch }
}

const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

function pptxDoc(): DocumentItem {
  return docOf({ content_type: 'pptx', asset_mime: PPTX_MIME, title: '胶片' })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }))
  vi.spyOn(documentsApi, 'assetPreviewBlob').mockResolvedValue(new Blob(['<html><body>预览</body></html>'], { type: 'text/html' }))
  vi.spyOn(documentsApi, 'assetPreviewText').mockResolvedValue(
    '<html><head><style>.cn-sheet-panel{display:none}</style></head><body><table class="sheet"><tbody><tr><td>预览</td></tr></tbody></table></body></html>',
  )
  // 默认「服务端 PDF 未启用」：除新增 PDF 用例外，PPTX 用例保持 0128 客户端预览行为
  vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status: 409, data: null })
  vi.spyOn(documentsApi, 'requestAssetPdf').mockResolvedValue({ status: 409 })
})

describe('DocumentAssetView 原件阅读器', () => {
  it('PDF 走 iframe 内联渲染，并显示格式标签（下载入口在顶栏，不再有内嵌下载按钮）', async () => {
    renderProviders(<DocumentAssetView workspaceId={7} doc={docOf({})} />)

    expect(await screen.findByTestId('doc-asset-pdf')).toBeInTheDocument()
    // 格式 / 只读标识统一在文档页顶栏，阅读器内部不再重复一行
    expect(screen.queryByTestId('doc-asset-format')).not.toBeInTheDocument()
    expect(screen.queryByTestId('doc-asset-download')).not.toBeInTheDocument()
    expect(documentsApi.assetBlob).toHaveBeenCalledWith(7, 31)
  })

  it('原件在 staleTime 内复用缓存，重挂载不重复下载', async () => {
    const doc = docOf({})
    const first = renderProviders(<DocumentAssetView workspaceId={7} doc={doc} />)
    await screen.findByTestId('doc-asset-pdf')
    expect(documentsApi.assetBlob).toHaveBeenCalledTimes(1)

    first.unmount()
    render(
      <QueryClientProvider client={first.queryClient}>
        <DocumentAssetView workspaceId={7} doc={doc} />
      </QueryClientProvider>,
    )
    await screen.findByTestId('doc-asset-pdf')
    expect(documentsApi.assetBlob).toHaveBeenCalledTimes(1)
  })

  it('图片走 <img> 渲染（不用 object，避免 SVG 脚本执行）', async () => {
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({ content_type: 'image', asset_mime: 'image/svg+xml', title: '图标' })}
      />,
    )

    const image = await screen.findByTestId('doc-asset-image')
    expect(image.tagName).toBe('IMG')
    expect(image).toHaveAttribute('alt', '图标')
    expect(screen.queryByTestId('doc-asset-format')).not.toBeInTheDocument()
  })

  it('xlsx 走后端 HTML 内联预览（Shadow DOM），不再给下载卡也不再套 iframe', async () => {
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({
          content_type: 'xlsx',
          asset_mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          title: '明细',
        })}
      />,
    )

    const host = await screen.findByTestId('doc-asset-office')
    expect(host.tagName).toBe('DIV')
    // 内容进影子根：样式隔离、正文区只有一条滚动条（与 PPTX 同模型）
    expect(host.shadowRoot?.innerHTML).toContain('<table class="sheet">')
    expect(host.shadowRoot?.innerHTML).toContain('.cn-sheet-panel{display:none}')
    expect(document.querySelector('iframe[data-testid="doc-asset-office"]')).toBeNull()
    expect(screen.queryByTestId('doc-asset-format')).not.toBeInTheDocument()
    expect(screen.queryByTestId('doc-asset-download-card')).not.toBeInTheDocument()
    expect(documentsApi.assetPreviewText).toHaveBeenCalledWith(7, 31)
  })

  it('archive 存档的 Word 文档同样走预览 iframe', async () => {
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({
          content_type: 'word',
          asset_mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          title: '说明书',
        })}
      />,
    )

    expect((await screen.findByTestId('doc-asset-office')).tagName).toBe('DIV')
    expect(screen.queryByTestId('doc-asset-format')).not.toBeInTheDocument()
    expect(assetSuffix(docOf({ content_type: 'word', asset_mime: '' }))).toBe('docx')
  })

  it('Office 预览失败退化下载卡（原件仍可下载）', async () => {
    vi.spyOn(documentsApi, 'assetPreviewText').mockRejectedValue(new Error('400'))
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({
          content_type: 'xlsx',
          asset_mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          title: '坏表',
        })}
      />,
    )

    const card = await screen.findByTestId('doc-asset-download-card')
    expect(card).toHaveTextContent('原件无法在线预览')
    expect(screen.queryByTestId('doc-asset-office')).not.toBeInTheDocument()
    expect(screen.queryByTestId('doc-asset-error')).not.toBeInTheDocument()
  })

  it('旧版 .xls / .ppt 给下载卡而不是内联预览', async () => {
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({ content_type: 'xlsx', asset_mime: 'application/vnd.ms-excel', title: '数据' })}
      />,
    )

    expect(await screen.findByTestId('doc-asset-download-card')).toHaveTextContent('不支持在线预览')
    expect(screen.queryByTestId('doc-asset-office')).not.toBeInTheDocument()
    expect(screen.queryByTestId('doc-pptx-present')).not.toBeInTheDocument()
  })

  it('PPTX 走懒加载在线预览，不再给下载卡', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(
      new Blob(['PK'], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }),
    )
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({
          content_type: 'pptx',
          asset_mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
          title: '胶片',
        })}
      />,
    )

    expect(await screen.findByTestId('pptx-preview-stub')).toHaveTextContent('胶片')
    expect(screen.queryByTestId('doc-asset-download-card')).not.toBeInTheDocument()
    // 放映入口已上移到文档页顶栏，阅读器内部不再重复按钮
    expect(screen.queryByTestId('doc-pptx-present')).not.toBeInTheDocument()
  })

  it('PPTX 放映覆盖层由页面状态驱动（presenting / onPresentingChange）', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(
      new Blob(['PK'], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }),
    )
    const onPresentingChange = vi.fn()
    const { rerender, ...utils } = renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({
          content_type: 'pptx',
          asset_mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
          title: '胶片',
        })}
        presenting
        onPresentingChange={onPresentingChange}
      />,
    )

    expect(await screen.findByTestId('pptx-slideshow-stub')).toHaveTextContent('胶片')
    fireEvent.click(screen.getByRole('button', { name: '退出放映' }))
    expect(onPresentingChange).toHaveBeenCalledWith(false)

    // 关闭后（presenting=false）不再渲染覆盖层
    rerender(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({
          content_type: 'pptx',
          asset_mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
          title: '胶片',
        })}
      />,
    )
    await waitFor(() => expect(screen.queryByTestId('pptx-slideshow-stub')).not.toBeInTheDocument())
    void utils
  })

  it('服务端 PDF 就绪后从客户端预览原位切换为 PDF iframe（ADR 0129）', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['PK'], { type: PPTX_MIME }))
    let releasePdf!: (value: { status: number; data: Blob | null }) => void
    vi.spyOn(documentsApi, 'assetPdf').mockReturnValue(new Promise(resolve => { releasePdf = resolve }))

    renderProviders(<DocumentAssetView workspaceId={7} doc={pptxDoc()} />)

    // 首屏不等待 PDF：先出 0128 客户端预览
    expect(await screen.findByTestId('pptx-preview-stub')).toHaveTextContent('胶片')
    expect(screen.queryByTestId('doc-asset-pptx-pdf')).not.toBeInTheDocument()

    releasePdf({ status: 200, data: new Blob(['%PDF-1.7'], { type: 'application/pdf' }) })

    const frame = await screen.findByTestId('doc-asset-pptx-pdf')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame).toHaveAttribute('src', expect.stringContaining('blob:'))
    expect(screen.queryByTestId('pptx-preview-stub')).not.toBeInTheDocument()
  })

  it('转换中只显示轻量提示，客户端预览保持可用', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['PK'], { type: PPTX_MIME }))
    vi.spyOn(documentsApi, 'assetPdf')
      .mockResolvedValueOnce({ status: 202, data: null })
      .mockResolvedValue({ status: 409, data: null })

    const { unmount } = renderProviders(<DocumentAssetView workspaceId={7} doc={pptxDoc()} />)

    expect(await screen.findByTestId('pptx-preview-stub')).toHaveTextContent('胶片')
    expect(await screen.findByTestId('doc-pptx-pdf-pending')).toHaveTextContent('正在生成高清预览')
    expect(screen.queryByTestId('doc-asset-pptx-pdf')).not.toBeInTheDocument()
    unmount()
  })

  it.each([409, 413, 422, 503] as const)('PDF 不可用（HTTP %s）静默保留客户端预览', async status => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['PK'], { type: PPTX_MIME }))
    vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({ status, data: null })

    renderProviders(<DocumentAssetView workspaceId={7} doc={pptxDoc()} />)

    expect(await screen.findByTestId('pptx-preview-stub')).toHaveTextContent('胶片')
    await waitFor(() => expect(documentsApi.assetPdf).toHaveBeenCalled())
    expect(screen.queryByTestId('doc-asset-pptx-pdf')).not.toBeInTheDocument()
    expect(screen.queryByTestId('doc-asset-error')).not.toBeInTheDocument()
  })

  it('转换失败后可手动重试一次（POST 触发 + 重新读取状态）', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['PK'], { type: PPTX_MIME }))
    vi.spyOn(documentsApi, 'assetPdf')
      .mockResolvedValueOnce({ status: 422, data: null })
      .mockResolvedValue({ status: 409, data: null })
    const requestSpy = vi.spyOn(documentsApi, 'requestAssetPdf').mockResolvedValue({ status: 202 })

    renderProviders(<DocumentAssetView workspaceId={7} doc={pptxDoc()} />)

    fireEvent.click(await screen.findByTestId('doc-pptx-pdf-retry'))

    await waitFor(() => expect(requestSpy).toHaveBeenCalledWith(7, 31))
    await waitFor(() => expect(documentsApi.assetPdf).toHaveBeenCalledTimes(2))
  })

  it('PDF objectURL 在卸载时释放', async () => {
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['PK'], { type: PPTX_MIME }))
    vi.spyOn(documentsApi, 'assetPdf').mockResolvedValue({
      status: 200,
      data: new Blob(['%PDF-1.7'], { type: 'application/pdf' }),
    })

    const { unmount } = renderProviders(<DocumentAssetView workspaceId={7} doc={pptxDoc()} />)
    await screen.findByTestId('doc-asset-pptx-pdf')
    unmount()

    expect(revokeSpy).toHaveBeenCalledWith(expect.stringContaining('blob:'))
  })

  it('旧版二进制 PPT 仍回落下载卡（纯前端渲染只支持 .pptx）', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(
      new Blob(['\xd0\xcf'], { type: 'application/vnd.ms-powerpoint' }),
    )
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({ content_type: 'pptx', asset_mime: 'application/vnd.ms-powerpoint', title: '旧版胶片' })}
      />,
    )

    expect(await screen.findByTestId('doc-asset-download-card')).toHaveTextContent('不支持在线预览')
    expect(screen.queryByTestId('pptx-preview-stub')).not.toBeInTheDocument()
    // 旧版 .ppt 不进入服务端转换链路
    expect(documentsApi.assetPdf).not.toHaveBeenCalled()
  })

  it('MIME 缺失时按 content_type 兜底扩展名（assetSuffix 共用于顶栏下载与下载卡）', () => {
    expect(assetSuffix(docOf({ content_type: 'pptx', asset_mime: '', title: '胶片' }))).toBe('pptx')
    expect(
      assetSuffix(
        docOf({
          content_type: 'xlsx',
          asset_mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          title: '明细',
        }),
      ),
    ).toBe('xlsx')
    expect(assetSuffix(docOf({}))).toBe('pdf')
    expect(assetSuffix(docOf({ content_type: 'mhtml', asset_mime: 'multipart/related' }))).toBe('')
  })

  it('原件读取失败显示「原件缺失」而非空白', async () => {
    vi.spyOn(documentsApi, 'assetBlob').mockRejectedValue(new Error('404'))
    renderProviders(<DocumentAssetView workspaceId={7} doc={docOf({})} />)

    expect(await screen.findByTestId('doc-asset-error')).toBeInTheDocument()
    expect(screen.getByText('原件缺失或无法读取')).toBeInTheDocument()
    expect(screen.queryByTestId('doc-asset-pdf')).not.toBeInTheDocument()
  })

  it('MHTML 走预览端点 + 沙箱 iframe（0064 C3）', async () => {
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({ content_type: 'mhtml', asset_mime: 'multipart/related', title: '网页存档' })}
      />,
    )

    const frame = await screen.findByTestId('doc-asset-mhtml')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame).toHaveAttribute('sandbox', '')
    // 预览单独走 preview 端点（下载在顶栏走原件端点）
    expect(documentsApi.assetPreviewBlob).toHaveBeenCalledWith(7, 31)
  })

  it('MHTML 预览失败退化为「原件缺失」提示', async () => {
    vi.spyOn(documentsApi, 'assetPreviewBlob').mockRejectedValue(new Error('400'))
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({ content_type: 'mhtml', asset_mime: 'multipart/related', title: '网页存档' })}
      />,
    )

    expect(await screen.findByTestId('doc-asset-error')).toBeInTheDocument()
    expect(screen.queryByTestId('doc-asset-mhtml')).not.toBeInTheDocument()
  })
})

/** 原件族阅读器测试（ADR 0025）：PDF / 图片 / Office 三种形态 + 失败态. */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import DocumentAssetView, { assetSuffix } from './DocumentAssetView'
import { renderProviders } from '@/test/render-providers'
import { documentsApi, type DocumentItem } from '@/api/documents'

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

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(documentsApi, 'assetBlob').mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }))
  vi.spyOn(documentsApi, 'assetPreviewBlob').mockResolvedValue(new Blob(['<html><body>预览</body></html>'], { type: 'text/html' }))
})

describe('DocumentAssetView 原件阅读器', () => {
  it('PDF 走 iframe 内联渲染，并显示格式标签（下载入口在顶栏，不再有内嵌下载按钮）', async () => {
    renderProviders(<DocumentAssetView workspaceId={7} doc={docOf({})} />)

    expect(await screen.findByTestId('doc-asset-pdf')).toBeInTheDocument()
    expect(screen.getByTestId('doc-asset-format')).toHaveTextContent('PDF')
    expect(screen.queryByTestId('doc-asset-download')).not.toBeInTheDocument()
    expect(documentsApi.assetBlob).toHaveBeenCalledWith(7, 31)
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
    expect(screen.getByTestId('doc-asset-format')).toHaveTextContent('图片')
  })

  it('Excel / PPT 给下载卡而不是内联预览', async () => {
    renderProviders(
      <DocumentAssetView
        workspaceId={7}
        doc={docOf({ content_type: 'xlsx', asset_mime: 'application/vnd.ms-excel', title: '数据' })}
      />,
    )

    expect(await screen.findByTestId('doc-asset-download-card')).toHaveTextContent('不支持在线预览')
    expect(screen.queryByTestId('doc-asset-pdf')).not.toBeInTheDocument()
  })

  it('MIME 缺失时按 content_type 兜底扩展名（assetSuffix 共用于顶栏下载与下载卡）', () => {
    expect(assetSuffix(docOf({ content_type: 'pptx', asset_mime: '', title: '胶片' }))).toBe('pptx')
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

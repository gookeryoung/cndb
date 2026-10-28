/** 原件族文档阅读器（ADR 0025）：PDF / 图片 / MHTML 直接渲染，Office 给下载卡.
 *
 * 原件经带鉴权头的接口取回为 blob，再挂 objectURL —— 不用裸链接，
 * 否则未发布草稿的原件会绕过文档可见性。
 * MHTML（0064）：浏览器不渲染 multipart/related 原件，改用后端生成的
 * 自包含预览 HTML，在禁脚本的沙箱 iframe 里渲染；下载仍走原件接口。
 */
import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Empty, Space, Spin, Tag, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { documentsApi, type DocumentItem } from '@/api/documents'
import { formatSize } from '@/utils/formatSize'
import { formatMeta } from '@/components/Document/docFormat'

const { Text } = Typography

interface Props {
  workspaceId: number
  doc: DocumentItem
}

/** 扩展名：优先用后端 MIME，缺失时退回 content_type */
function suffixOf(doc: DocumentItem): string {
  const mime = doc.asset_mime ?? ''
  const byMime: Record<string, string> = {
    'application/pdf': 'pdf',
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
    'image/bmp': 'bmp',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.ms-powerpoint': 'ppt',
  }
  if (byMime[mime]) return byMime[mime]
  return doc.content_type === 'xlsx' ? 'xlsx' : doc.content_type === 'pptx' ? 'pptx' : ''
}

export default function DocumentAssetView({ workspaceId, doc }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const fmt = formatMeta(doc.content_type)
  const suffix = suffixOf(doc)
  const isMhtml = doc.content_type === 'mhtml'

  const assetQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset'],
    queryFn: () => documentsApi.assetBlob(workspaceId, doc.id),
    retry: false,
  })

  // MHTML 预览与原件下载分开取：预览是转换后的自包含 HTML，不能混用
  const previewQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset-preview'],
    queryFn: () => documentsApi.assetPreviewBlob(workspaceId, doc.id),
    retry: false,
    enabled: isMhtml,
  })

  const blob = assetQuery.data
  useEffect(() => {
    if (!blob) {
      setObjectUrl(null)
      return
    }
    const url = URL.createObjectURL(blob)
    setObjectUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [blob])

  const previewBlob = previewQuery.data
  useEffect(() => {
    if (!previewBlob) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(previewBlob)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [previewBlob])

  const loading = isMhtml ? previewQuery.isLoading : assetQuery.isLoading
  const failed = isMhtml ? previewQuery.isError || !previewUrl : assetQuery.isError || !objectUrl

  const downloadName = useMemo(() => `${doc.title || 'download'}${suffix ? `.${suffix}` : ''}`, [doc.title, suffix])

  const header = (
    <Space size={8} wrap style={{ marginBottom: 12 }}>
      <Tag color="default" data-testid="doc-asset-format">
        {fmt.label}
      </Tag>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {formatSize(doc.content_size)} · 原样存档（只读）
      </Text>
      <Button
        size="small"
        icon={<DownloadOutlined />}
        disabled={!objectUrl}
        href={objectUrl ?? undefined}
        download={downloadName}
        data-testid="doc-asset-download"
      >
        下载原件
      </Button>
    </Space>
  )

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (failed) {
    return (
      <div style={{ padding: 24 }} data-testid="doc-asset-error">
        {header}
        <Alert
          type="warning"
          showIcon
          message="原件缺失或无法读取"
          description="该文档的原件可能已被清理，请联系上传者重新导入。"
        />
      </div>
    )
  }

  const viewer = (() => {
    if (doc.content_type === 'pdf') {
      return (
        <iframe
          title={doc.title}
          src={objectUrl ?? undefined}
          data-testid="doc-asset-pdf"
          style={{ flex: 1, minHeight: 0, width: '100%', border: 'none' }}
        />
      )
    }
    if (doc.content_type === 'image') {
      return (
        <div
          style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          {/* 用 <img> 而非 <object>：SVG 里的脚本不会执行 */}
          <img
            src={objectUrl ?? undefined}
            alt={doc.title}
            data-testid="doc-asset-image"
            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
          />
        </div>
      )
    }
    if (doc.content_type === 'mhtml') {
      // MHTML 预览（0064 C3）：后端自包含 HTML，沙箱 iframe 渲染——
      // sandbox 空值 = 禁脚本、禁同源、禁表单；网页存档视为不可信内容
      return (
        <iframe
          title={doc.title}
          src={previewUrl ?? undefined}
          sandbox=""
          data-testid="doc-asset-mhtml"
          style={{ flex: 1, minHeight: 0, width: '100%', border: 'none' }}
        />
      )
    }
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={`${fmt.label} 文件不支持在线预览，请下载后查看`}
        style={{ marginTop: 64 }}
        data-testid="doc-asset-download-card"
      >
        <Button type="primary" icon={<DownloadOutlined />} href={objectUrl ?? undefined} download={downloadName}>
          下载原件
        </Button>
      </Empty>
    )
  })()

  return (
    <div
      style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: '12px 24px' }}
      data-testid="doc-asset-view"
    >
      {header}
      {viewer}
    </div>
  )
}

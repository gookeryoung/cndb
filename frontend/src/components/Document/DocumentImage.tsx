/** 文档内图片渲染：站内 `file:<key>` 走鉴权取 blob，外部 URL 直接渲染. */

import { Image, Typography } from 'antd'

import { useFileObjectUrl } from '@/hooks/useFileObjectUrl'
import { parseImageRef } from './imageRef'

interface DocumentImageProps {
  workspaceId?: number | string
  src?: string
  alt?: string
}

export default function DocumentImage({ workspaceId, src, alt }: DocumentImageProps) {
  const fileKey = parseImageRef(src)
  // 非站内引用时 hook 内部直接置空（enabled=false），不会发请求
  const { url, error } = useFileObjectUrl(workspaceId, fileKey)

  if (!fileKey) {
    return (
      <img
        src={src}
        alt={alt}
        loading="lazy"
        data-testid="doc-image-external"
        className="cn-doc-image"
      />
    )
  }

  // 缺少工作区上下文（或加载失败）时给出可读提示，避免空白
  if (error || workspaceId === undefined || workspaceId === null) {
    return (
      <Typography.Text type="secondary" className="cn-doc-image-missing" data-testid="doc-image-missing">
        图片加载失败（{fileKey}）
      </Typography.Text>
    )
  }

  if (!url) {
    // 仍在取 blob：占位避免布局跳动
    return <span className="cn-doc-image-placeholder" data-testid="doc-image-loading" aria-label="图片加载中" />
  }

  return (
    <Image
      src={url}
      alt={alt}
      className="cn-doc-image"
      data-testid="doc-image-inline"
      // 站内图片可能较大：预览时限制在正文宽度内，点击可放大
      style={{ maxWidth: '100%' }}
      preview={{ mask: '预览' }}
    />
  )
}

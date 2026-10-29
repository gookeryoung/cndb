/** 文档内图片渲染：站内 `file:<key>` 走鉴权取 blob（公开分享页走免登录 URL），外部 URL 直接渲染. */

import { Image, Typography } from 'antd'

import { useFileObjectUrl } from '@/hooks/useFileObjectUrl'
import { useDocSettingsStore } from '@/store'
import { parseImageRef } from './imageRef'

interface DocumentImageProps {
  workspaceId?: number | string
  /** 公开分享页的免登录图片基地址：提供后站内图片直接拼 URL，不再取 blob */
  publicFileBase?: string
  src?: string
  alt?: string
}

export default function DocumentImage({ workspaceId, publicFileBase, src, alt }: DocumentImageProps) {
  const fileKey = parseImageRef(src)
  // 个人设置（文档页签）：图片默认显示宽度（百分比）
  const imageWidth = useDocSettingsStore(s => s.imageDefaultWidth)
  // 非站内引用（或公开页已走免登录 URL）时 hook 内部直接置空，不会发请求
  const { url, error } = useFileObjectUrl(publicFileBase ? undefined : workspaceId, fileKey)

  if (!fileKey) {
    return (
      <img
        src={src}
        alt={alt}
        loading="lazy"
        data-testid="doc-image-external"
        className="cn-doc-image"
        style={{ width: `${imageWidth}%` }}
        // 公开页 URL 含 token：外部图片不接收 Referer，避免链接经第三方泄露
        referrerPolicy={publicFileBase ? 'no-referrer' : undefined}
      />
    )
  }

  if (publicFileBase) {
    return (
      <Image
        src={`${publicFileBase}/${fileKey}`}
        alt={alt}
        className="cn-doc-image"
        data-testid="doc-image-public"
        style={{ width: `${imageWidth}%`, maxWidth: '100%' }}
        preview={{ mask: '预览' }}
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
      // 站内图片可能较大：按个人设置的默认宽度显示，上限正文宽度，点击可放大
      style={{ width: `${imageWidth}%`, maxWidth: '100%' }}
      preview={{ mask: '预览' }}
    />
  )
}

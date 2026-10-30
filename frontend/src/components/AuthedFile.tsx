/** 带鉴权的附件渲染组件.
 *
 * `<img src>` / `<a href>` 无法携带 Authorization 头，认证开启时直连附件
 * 端点会 403（表现为「图片裂开」）。这里复用 `useFileObjectUrl`：
 * 先用 axios 拉 blob，再把 object URL 交给图片/链接。
 */

import { useState, type CSSProperties, type ReactNode } from 'react'
import { Image } from 'antd'
import type { ImageProps } from 'antd'
import { useFileObjectUrl, type FileId } from '@/hooks/useFileObjectUrl'

export function AuthedImage({
  wid,
  fileKey,
  alt,
  width = 48,
  height = 48,
  style,
  thumb,
  ...rest
}: ImageProps & { wid?: FileId; fileKey: string; thumb?: number }) {
  // 缩略图用于展示；原图只在预览要打开 / 鼠标悬停时才懒加载，避免为 32px 预览拉原图
  const [previewVisible, setPreviewVisible] = useState(false)
  const [preferFull, setPreferFull] = useState(!thumb)
  const { url: thumbUrl } = useFileObjectUrl(wid, fileKey, true, { thumb, enabled: !!thumb })
  const { url: fullUrl } = useFileObjectUrl(wid, fileKey, true, { enabled: preferFull })
  const url = thumb ? (thumbUrl ?? fullUrl) : fullUrl

  // 加载中/失败：渲染同尺寸占位块，避免浏览器「图裂」图标
  if (!url) {
    return (
      <span
        aria-hidden
        style={{ display: 'inline-block', width, height, background: '#f1f5f9', borderRadius: 4, ...style }}
      />
    )
  }
  return (
    <Image
      src={url}
      alt={alt}
      width={width}
      height={height}
      style={style}
      onMouseEnter={thumb ? () => setPreferFull(true) : undefined}
      preview={thumb ? {
        src: fullUrl,
        // antd 6：Image 预览 visible/onVisibleChange 改为 open/onOpenChange
        open: previewVisible,
        onOpenChange: visible => {
          setPreviewVisible(visible)
          if (visible) setPreferFull(true)
        },
      } : undefined}
      {...rest}
    />
  )
}

export function AuthedFileLink({
  wid,
  fileKey,
  filename,
  children,
  style,
}: {
  wid?: FileId
  fileKey: string
  filename: string
  children?: ReactNode
  style?: CSSProperties
}) {
  const { url } = useFileObjectUrl(wid, fileKey, false)
  return (
    <a
      href={url}
      download={url ? filename : undefined}
      target={url ? undefined : '_self'}
      rel="noreferrer"
      style={{ ...style, pointerEvents: url ? undefined : 'none', opacity: url ? 1 : 0.5 }}
      aria-disabled={!url}
    >
      {children ?? filename}
    </a>
  )
}

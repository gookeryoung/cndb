/** 带鉴权的附件渲染组件.
 *
 * `<img src>` / `<a href>` 无法携带 Authorization 头，认证开启时直连附件
 * 端点会 403（表现为「图片裂开」）。这里复用 `useFileObjectUrl`：
 * 先用 axios 拉 blob，再把 object URL 交给图片/链接。
 */

import type { CSSProperties, ReactNode } from 'react'
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
  ...rest
}: ImageProps & { wid?: FileId; fileKey: string }) {
  const { url } = useFileObjectUrl(wid, fileKey, true)

  // 加载中/失败：渲染同尺寸占位块，避免浏览器「图裂」图标
  if (!url) {
    return (
      <span
        aria-hidden
        style={{ display: 'inline-block', width, height, background: '#f1f5f9', borderRadius: 4, ...style }}
      />
    )
  }
  return <Image src={url} alt={alt} width={width} height={height} style={style} {...rest} />
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

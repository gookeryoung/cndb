/** PPTX 在线预览（原始 .pptx 原件族）：纯前端解析 zip + 渲染幻灯片，不依赖后端转换.
 *
 * 体积边界：`pptx-preview` 及其依赖（jszip / echarts 等）只在打开 .pptx 时按需下载，
 * 本组件由 DocumentAssetView 以 React.lazy 挂载，不进文档页首屏 chunk。
 * 失败（非 zip / 解析异常 / 加密 PPTX）回落到错误提示，下载入口仍在编辑页顶栏。
 */

import { useEffect, useRef, useState } from 'react'
import { Alert, Spin } from 'antd'

interface Props {
  blob: Blob
  title: string
}

export default function PptxPreview({ blob, title }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let cancelled = false
    let viewer: { destroy: () => void; preview: (buffer: ArrayBuffer) => Promise<unknown> } | null = null
    host.innerHTML = ''
    setStatus('loading')

    void (async () => {
      try {
        const [{ init }, buffer] = await Promise.all([import('pptx-preview'), blob.arrayBuffer()])
        if (cancelled) return
        // 幻灯片按容器宽度缩放（1024 上限避免超宽屏横向拉伸；窄屏保底 320 并横向滚动）
        const width = Math.min(Math.max(host.clientWidth || 960, 320), 1024)
        viewer = init(host, { width, mode: 'list' })
        await viewer.preview(buffer)
        if (!cancelled) setStatus('ready')
      } catch {
        if (!cancelled) setStatus('error')
      }
    })()

    return () => {
      cancelled = true
      viewer?.destroy()
      host.innerHTML = ''
    }
  }, [blob])

  return (
    <div
      className="cn-pptx-preview"
      data-testid="doc-asset-pptx"
      style={{ flex: 1, minHeight: 0, overflow: 'auto', position: 'relative' }}
    >
      {status === 'error' ? (
        <Alert
          type="warning"
          showIcon
          data-testid="doc-asset-pptx-error"
          title={`「${title || 'PPTX'}」无法在线渲染`}
          description="原件可能已损坏、加密或不是标准 .pptx；请从顶栏下载后查看。"
          style={{ margin: 16 }}
        />
      ) : (
        <>
          <div ref={hostRef} />
          {status === 'loading' && (
            <div
              style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >
              <Spin />
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** PPTX 在线预览（原始 .pptx 原件族）：纯前端解析 zip + 逐页渲染，不依赖后端转换.
 *
 * 体积边界：`pptx-preview` 及其依赖（jszip / echarts 等）只在打开 .pptx 时按需下载，
 * 本组件由 DocumentAssetView 以 React.lazy 挂载，不进文档页首屏 chunk。
 * 性能边界（需求 0128 C1）：slide 模式一次只渲染当前页，不再等整份 PPT 全部渲染；
 * 失败（非 zip / 解析异常 / 加密 PPTX）回落到错误提示，下载入口仍在编辑页顶栏。
 */

import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Spin, Typography } from 'antd'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { loadPptxModule } from './pptxLoader'

const { Text } = Typography

interface Props {
  blob: Blob
  title: string
}

interface Viewer {
  destroy: () => void
  preview: (buffer: ArrayBuffer) => Promise<unknown>
  renderSingleSlide: (index: number) => void
  slideCount: number
}

export default function PptxPreview({ blob, title }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer | null>(null)
  const indexRef = useRef(0)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [index, setIndex] = useState(0)
  const [count, setCount] = useState(0)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let cancelled = false
    let viewer: Viewer | null = null
    host.innerHTML = ''
    host.style.lineHeight = '0'
    viewerRef.current = null
    indexRef.current = 0
    setStatus('loading')
    setIndex(0)
    setCount(0)

    void (async () => {
      try {
        const [{ init }, buffer] = await Promise.all([loadPptxModule(), blob.arrayBuffer()])
        if (cancelled) return
        // 幻灯片按容器宽度缩放（1024 上限避免超宽屏横向拉伸；窄屏保底 320 并横向滚动）
        const containerWidth = host.parentElement?.clientWidth ?? 0
        const width = Math.min(Math.max(containerWidth || 960, 320), 1024)
        // 高度至少覆盖 4:3 幻灯片，避免只按 16:9 计算时裁切；超宽容器仍按实际高度
        const containerHeight = host.parentElement?.clientHeight ?? 0
        const height = Math.max(containerHeight, Math.round(width * 0.75))
        host.style.width = `${width}px`
        host.style.margin = '0 auto'

        viewer = init(host, { width, height, mode: 'slide' }) as Viewer
        viewerRef.current = viewer
        await viewer.preview(buffer)
        if (cancelled) return
        // 库里自带的翻页按钮 / 页码与底部控制条重复，移除后只保留本组件的控制
        host.querySelectorAll('.pptx-preview-wrapper-next, .pptx-preview-wrapper-pagination')
          .forEach(element => element.remove())
        setCount(viewer.slideCount)
        setIndex(0)
        setStatus('ready')
      } catch {
        viewer?.destroy()
        viewer = null
        viewerRef.current = null
        host.innerHTML = ''
        if (!cancelled) setStatus('error')
      }
    })()

    return () => {
      cancelled = true
      viewer?.destroy()
      viewer = null
      viewerRef.current = null
      host.innerHTML = ''
    }
  }, [blob])

  const go = (next: number) => {
    const viewer = viewerRef.current
    if (!viewer || status !== 'ready') return
    const bounded = Math.max(0, Math.min(next, viewer.slideCount - 1))
    if (bounded === indexRef.current) return
    viewer.renderSingleSlide(bounded)
    indexRef.current = bounded
    setIndex(bounded)
  }

  return (
    <div
      className="cn-pptx-preview"
      data-testid="doc-asset-pptx"
      style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', position: 'relative' }}
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
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', position: 'relative' }}>
            <div ref={hostRef} />
            {status === 'loading' && (
              <div
                style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >
                <Spin />
              </div>
            )}
          </div>
          {status === 'ready' && count > 0 && (
            <div
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12,
                paddingTop: 8, flexShrink: 0,
              }}
            >
              <Button
                size="small"
                type="text"
                icon={<LeftOutlined />}
                aria-label="上一页"
                disabled={index <= 0}
                onClick={() => go(index - 1)}
              />
              <Text type="secondary" data-testid="doc-pptx-preview-index" aria-live="polite">
                {index + 1} / {count}
              </Text>
              <Button
                size="small"
                type="text"
                icon={<RightOutlined />}
                aria-label="下一页"
                disabled={index >= count - 1}
                onClick={() => go(index + 1)}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}

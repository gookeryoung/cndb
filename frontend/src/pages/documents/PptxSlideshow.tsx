/** PPTX 全屏放映：在独立覆盖层里用 slide 模式渲染单页，支持键盘 / 按钮翻页.
 *
 * 覆盖层挂载时尝试调用 Fullscreen API（不可用或用户拒绝时退化为固定全屏覆盖层）；
 * 退出全屏 / Esc / 关闭按钮都会回到文档阅读器。渲染库仍走按需加载。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Spin, Typography } from 'antd'
import { CloseOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'

const { Text } = Typography

interface Props {
  blob: Blob
  title: string
  onClose: () => void
}

export default function PptxSlideshow({ blob, title, onClose }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<{
    destroy: () => void
    preview: (buffer: ArrayBuffer) => Promise<unknown>
    renderSingleSlide: (index: number) => void
    slideCount: number
  } | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [index, setIndex] = useState(0)
  const [count, setCount] = useState(0)
  // 键盘监听只注册一次：用 ref 读取最新页码 / 状态，避免闭包过期
  const indexRef = useRef(0)
  const statusRef = useRef<'loading' | 'ready' | 'error'>('loading')
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  // 已经真正进入全屏 / 正在退出：用于区分「浏览器 Esc 退出」与清理或重复事件
  const enteredFullscreenRef = useRef(false)
  const closingRef = useRef(false)

  // 全屏覆盖层 + 退出全屏时自动关闭（用户按浏览器 Esc 也走这里）
  useEffect(() => {
    const el = overlayRef.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onFullscreenChange = () => {
      if (document.fullscreenElement === el) {
        enteredFullscreenRef.current = true
        return
      }
      // 只有「确实进入过全屏」后的退出才算用户主动退出；
      // React StrictMode 的 effect 清理 / 首次请求竞态不会触发 onClose
      if (enteredFullscreenRef.current && !closingRef.current) {
        closingRef.current = true
        onCloseRef.current()
      }
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)

    const request = el?.requestFullscreen?.()
    if (request) void request.catch(() => undefined)

    return () => {
      document.removeEventListener('fullscreenchange', onFullscreenChange)
      document.body.style.overflow = previousOverflow
      // 不在清理里主动 exitFullscreen：退出统一走 close 回调，
      // 否则 StrictMode 的二次执行会「刚进全屏就被退出」
    }
  }, [])

  /** 退出放映：先退出全屏再通知父组件卸载，退出事件由 closingRef 吞掉 */
  const close = useCallback(() => {
    closingRef.current = true
    if (document.fullscreenElement) {
      const exit = document.exitFullscreen?.()
      if (exit) void exit.catch(() => undefined)
    }
    onCloseRef.current()
  }, [])

  // 解析并渲染第一页
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let cancelled = false
    host.innerHTML = ''
    statusRef.current = 'loading'
    setStatus('loading')

    void (async () => {
      try {
        const [{ init }, buffer] = await Promise.all([import('pptx-preview'), blob.arrayBuffer()])
        if (cancelled) return
        // 幻灯片按视口缩放：留出底部控制条与四周留白
        const maxWidth = Math.min(Math.max(window.innerWidth - 96, 320), 1600)
        const maxHeight = Math.min(Math.max(window.innerHeight - 140, 200), 1000)

        const createViewer = async (width: number) => {
          host.innerHTML = ''
          const instance = init(host, { width, height: maxHeight, mode: 'slide' })
          viewerRef.current = instance
          await instance.preview(buffer)
          // 库自带的翻页按钮 / 页码与底部控制条重复，移除后只保留本组件的控制
          host.querySelectorAll('.pptx-preview-wrapper-next, .pptx-preview-wrapper-pagination')
            .forEach(element => element.remove())
          return instance
        }

        // 先按常见 16:9 排版；若实际幻灯片更高（如 4:3）超出可用高度，按实际比例重排一次
        let viewer = await createViewer(Math.min(maxWidth, Math.round(maxHeight * 16 / 9)))
        if (cancelled) return
        const slide = host.querySelector('.pptx-preview-slide-wrapper') as HTMLElement | null
        if (slide && slide.offsetHeight > maxHeight + 1) {
          const ratio = slide.offsetWidth / Math.max(slide.offsetHeight, 1)
          viewer.destroy()
          viewer = await createViewer(Math.max(320, Math.round(maxHeight * ratio)))
          if (cancelled) return
        }

        setCount(viewer.slideCount)
        indexRef.current = 0
        setIndex(0)
        statusRef.current = 'ready'
        setStatus('ready')
      } catch {
        if (!cancelled) {
          statusRef.current = 'error'
          setStatus('error')
        }
      }
    })()

    return () => {
      cancelled = true
      viewerRef.current?.destroy()
      viewerRef.current = null
      host.innerHTML = ''
    }
  }, [blob])

  const go = useCallback((next: number) => {
    const viewer = viewerRef.current
    if (!viewer || statusRef.current !== 'ready') return
    const bounded = Math.max(0, Math.min(next, viewer.slideCount - 1))
    if (bounded === indexRef.current) return
    viewer.renderSingleSlide(bounded)
    indexRef.current = bounded
    setIndex(bounded)
  }, [])

  // 键盘翻页：→ / ↓ / 空格 / PageDown 下一页，← / ↑ / PageUp 上一页，Esc 关闭
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
        return
      }
      if (['ArrowRight', 'ArrowDown', ' ', 'PageDown'].includes(event.key)) {
        event.preventDefault()
        go(indexRef.current + 1)
      } else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key)) {
        event.preventDefault()
        go(indexRef.current - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close, go])

  return (
    <div
      ref={overlayRef}
      className="cn-pptx-slideshow"
      data-testid="doc-asset-pptx-slideshow"
      role="dialog"
      aria-modal="true"
      aria-label={`${title || 'PPTX'} 放映`}
      style={{
        position: 'fixed', inset: 0, zIndex: 1200, background: '#000',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      }}
    >
      {status === 'error' ? (
        <Text style={{ color: '#fff' }}>无法放映：原件可能已损坏或加密，请退出后下载查看。</Text>
      ) : (
        <div ref={hostRef} style={{ lineHeight: 0 }} />
      )}

      {status === 'loading' && <Spin style={{ position: 'absolute' }} />}

      {/* 左右点击区：点击左侧上一页、点击右侧下一页（底部控制条区域留空避免遮挡） */}
      <button
        type="button"
        className="cn-pptx-nav-zone cn-pptx-nav-zone-prev"
        aria-label="点击左侧上一页"
        disabled={status !== 'ready' || index <= 0}
        onClick={() => go(index - 1)}
      >
        <LeftOutlined />
      </button>
      <button
        type="button"
        className="cn-pptx-nav-zone cn-pptx-nav-zone-next"
        aria-label="点击右侧下一页"
        disabled={status !== 'ready' || count === 0 || index >= count - 1}
        onClick={() => go(index + 1)}
      >
        <RightOutlined />
      </button>

      {/* 底部控制条：上一页 / 页码 / 下一页 / 退出放映 */}
      <div
        style={{
          position: 'absolute', bottom: 16, left: 0, right: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16,
        }}
      >
        <Button
          ghost
          icon={<LeftOutlined />}
          aria-label="上一页"
          disabled={status !== 'ready' || index <= 0}
          onClick={() => go(index - 1)}
        />
        <Text style={{ color: '#fff', minWidth: 56, textAlign: 'center' }} data-testid="doc-pptx-slide-index">
          {count > 0 ? `${index + 1} / ${count}` : '—'}
        </Text>
        <Button
          ghost
          icon={<RightOutlined />}
          aria-label="下一页"
          disabled={status !== 'ready' || count === 0 || index >= count - 1}
          onClick={() => go(index + 1)}
        />
        <Button
          ghost
          icon={<CloseOutlined />}
          aria-label="退出放映"
          onClick={close}
          style={{ marginLeft: 16 }}
        >
          退出放映
        </Button>
      </div>
    </div>
  )
}

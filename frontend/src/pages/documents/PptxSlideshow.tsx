/** PPTX 全屏放映：在独立覆盖层里用 slide 模式渲染单页，支持键盘 / 按钮 / 左右点击区翻页.
 *
 * - 覆盖层挂载时尝试调用 Fullscreen API（不可用或用户拒绝时退化为固定全屏覆盖层）；
 * - 临时标记笔：在幻灯片上覆盖一层 canvas 自由绘制，仅本次放映有效（换页 / 退出即清空）；
 * - 缩放：0.5x–2.5x 缩放整个舞台，标记笔随之缩放，坐标按显示尺寸换算；
 * - 记忆：页码按 ``storageKey`` 写入 localStorage，退出后再进入从上次放映页继续；
 * - 退出全屏 / Esc / 关闭按钮都会回到文档阅读器。渲染库仍走按需加载。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { Button, Spin, Typography } from 'antd'
import {
  CloseOutlined, DeleteOutlined, EditOutlined, LeftOutlined, MinusOutlined,
  PlusOutlined, RightOutlined,
} from '@ant-design/icons'
import { loadPptxModule } from './pptxLoader'

const { Text } = Typography

const MIN_ZOOM = 0.5
const MAX_ZOOM = 2.5
const ZOOM_STEP = 0.25

interface Props {
  blob: Blob
  title: string
  /** 页码记忆键（通常是 workspaceId + docId）；为空则不持久化 */
  storageKey?: string
  onClose: () => void
}

interface Viewer {
  destroy: () => void
  preview: (buffer: ArrayBuffer) => Promise<unknown>
  renderSingleSlide: (index: number) => void
  slideCount: number
}

interface CanvasBox {
  left: number
  top: number
  width: number
  height: number
}

export default function PptxSlideshow({ blob, title, storageKey, onClose }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawingRef = useRef(false)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [index, setIndex] = useState(0)
  const [count, setCount] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [penOn, setPenOn] = useState(false)
  const [hasMarks, setHasMarks] = useState(false)
  const [canvasBox, setCanvasBox] = useState<CanvasBox | null>(null)
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

  /** 清空标记笔（换页 / 退出 / 点击清除时调用） */
  const clearMarks = useCallback(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height)
    setHasMarks(false)
  }, [])

  // 解析并渲染第一页（放映页恢复由 storageKey 决定）
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let cancelled = false
    host.innerHTML = ''
    statusRef.current = 'loading'
    setStatus('loading')
    setCanvasBox(null)

    void (async () => {
      try {
        const [{ init }, buffer] = await Promise.all([loadPptxModule(), blob.arrayBuffer()])
        if (cancelled) return
        // 幻灯片按视口缩放：留出底部控制条与四周留白
        const maxWidth = Math.min(Math.max(window.innerWidth - 96, 320), 1600)
        const maxHeight = Math.min(Math.max(window.innerHeight - 160, 200), 1000)

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
        const findSlide = () => host.querySelector<HTMLElement>('.pptx-preview-slide-wrapper')
        const firstSlide = findSlide()
        if (firstSlide && firstSlide.offsetHeight > maxHeight + 1) {
          const ratio = firstSlide.offsetWidth / Math.max(firstSlide.offsetHeight, 1)
          viewer.destroy()
          viewer = await createViewer(Math.max(320, Math.round(maxHeight * ratio)))
          if (cancelled) return
        }

        // 上次放映页：读 localStorage，越界钳制到末页
        const saved = storageKey ? Number(window.localStorage.getItem(storageKey)) : 0
        const startIndex = Number.isFinite(saved)
          ? Math.max(0, Math.min(Math.trunc(saved), viewer.slideCount - 1))
          : 0
        if (startIndex > 0) viewer.renderSingleSlide(startIndex)
        indexRef.current = startIndex
        setIndex(startIndex)
        setCount(viewer.slideCount)

        // 标记画布覆盖在幻灯片上（不含黑边），换页尺寸不变可复用
        const wrapper = host.querySelector<HTMLElement>('.pptx-preview-wrapper')
        const slide = findSlide()
        if (wrapper && slide) {
          setCanvasBox({
            left: wrapper.offsetLeft + slide.offsetLeft,
            top: wrapper.offsetTop + slide.offsetTop,
            width: slide.offsetWidth,
            height: slide.offsetHeight,
          })
        }
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
  }, [blob, storageKey])

  // 画布尺寸跟随幻灯片布局尺寸；改尺寸会清空内容，同时复位「有标记」状态
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !canvasBox) return
    canvas.width = Math.max(1, Math.round(canvasBox.width))
    canvas.height = Math.max(1, Math.round(canvasBox.height))
    setHasMarks(false)
  }, [canvasBox])

  // 每次换页记录页码，供下次进入时恢复；换页同时清空临时标记
  useEffect(() => {
    if (status !== 'ready') return
    if (storageKey) {
      try {
        window.localStorage.setItem(storageKey, String(index))
      } catch {
        // 隐私模式 / 配额不可用时忽略，不影响放映
      }
    }
    clearMarks()
  }, [clearMarks, index, status, storageKey])

  const go = useCallback((next: number) => {
    const viewer = viewerRef.current
    if (!viewer || statusRef.current !== 'ready') return
    const bounded = Math.max(0, Math.min(next, viewer.slideCount - 1))
    if (bounded === indexRef.current) return
    viewer.renderSingleSlide(bounded)
    indexRef.current = bounded
    setIndex(bounded)
  }, [])

  const changeZoom = (delta: number) => {
    setZoom(prev => {
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, prev + delta))
      return Math.round(next * 100) / 100
    })
  }

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

  /** 标记笔坐标：按画布实际显示尺寸换算，兼容缩放 */
  const canvasPoint = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const canvas = event.currentTarget
    const rect = canvas.getBoundingClientRect()
    return {
      x: (event.clientX - rect.left) * (canvas.width / Math.max(rect.width, 1)),
      y: (event.clientY - rect.top) * (canvas.height / Math.max(rect.height, 1)),
    }
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!penOn) return
    const ctx = event.currentTarget.getContext('2d')
    if (!ctx) return
    drawingRef.current = true
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const { x, y } = canvasPoint(event)
    ctx.strokeStyle = '#e11d48'
    ctx.lineWidth = 3
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.beginPath()
    ctx.moveTo(x, y)
    setHasMarks(true)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!penOn || !drawingRef.current) return
    const ctx = event.currentTarget.getContext('2d')
    if (!ctx) return
    const { x, y } = canvasPoint(event)
    ctx.lineTo(x, y)
    ctx.stroke()
  }

  const endStroke = () => {
    drawingRef.current = false
  }

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
        overflow: 'hidden',
      }}
    >
      {status === 'error' ? (
        <Text style={{ color: '#fff' }}>无法放映：原件可能已损坏或加密，请退出后下载查看。</Text>
      ) : (
        <div
          data-testid="doc-pptx-stage"
          style={{
            position: 'relative',
            transform: `scale(${zoom})`,
            transformOrigin: 'center center',
            transition: 'transform 0.15s ease',
          }}
        >
          <div ref={hostRef} style={{ lineHeight: 0 }} />
          {canvasBox && (
            <canvas
              ref={canvasRef}
              data-testid="doc-pptx-mark-canvas"
              aria-label="临时标记画布"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={endStroke}
              onPointerLeave={endStroke}
              onPointerCancel={endStroke}
              style={{
                position: 'absolute',
                left: canvasBox.left,
                top: canvasBox.top,
                width: canvasBox.width,
                height: canvasBox.height,
                zIndex: 2,
                pointerEvents: penOn ? 'auto' : 'none',
                cursor: penOn ? 'crosshair' : 'default',
                touchAction: 'none',
              }}
            />
          )}
        </div>
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

      {/* 底部控制条：标记笔 / 缩放 + 上一页 / 页码 / 下一页 + 退出放映 */}
      <div
        style={{
          position: 'absolute', bottom: 16, left: 24, right: 24,
          display: 'flex', alignItems: 'center', gap: 12,
          // 半透明深色条：幻灯片全白时白色图标 / 页码仍然可见
          padding: '6px 12px',
          background: 'rgba(0, 0, 0, 0.55)',
          borderRadius: 'var(--cn-radius-pill)',
          backdropFilter: 'blur(6px)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Button
            ghost
            icon={<EditOutlined />}
            aria-label="标记笔"
            aria-pressed={penOn}
            title="临时标记笔（仅本次放映有效）"
            type={penOn ? 'primary' : 'default'}
            onClick={() => setPenOn(v => !v)}
          />
          <Button
            ghost
            icon={<DeleteOutlined />}
            aria-label="清除标记"
            disabled={!hasMarks}
            onClick={clearMarks}
          />
          <Button
            ghost
            icon={<MinusOutlined />}
            aria-label="缩小"
            disabled={zoom <= MIN_ZOOM}
            onClick={() => changeZoom(-ZOOM_STEP)}
          />
          <Button
            ghost
            aria-label="重置缩放"
            style={{ minWidth: 56 }}
            onClick={() => setZoom(1)}
          >
            {Math.round(zoom * 100)}%
          </Button>
          <Button
            ghost
            icon={<PlusOutlined />}
            aria-label="放大"
            disabled={zoom >= MAX_ZOOM}
            onClick={() => changeZoom(ZOOM_STEP)}
          />
        </div>

        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16 }}>
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
        </div>

        <Button
          ghost
          icon={<CloseOutlined />}
          aria-label="退出放映"
          onClick={close}
        >
          退出放映
        </Button>
      </div>
    </div>
  )
}

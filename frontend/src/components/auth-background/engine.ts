/** 认证页背景引擎：唯一生命周期入口（ADR 0016 §2 / I2 / I4 / I5 / I7）.
 *
 * 职责：DPR 与尺寸、单 rAF 循环、可见性暂停、resize 节流、桌面指针扰动、dispose。
 * 流场动效只负责「拿到 FrameContext 后画什么」，不碰定时器与监听。
 */

import { createFlowField } from './flowfield'
import { readPalette } from './palette'
import type { FrameContext, Palette } from './types'

export interface MountAuthBackgroundOptions {
  isMobile: boolean
  reducedMotion: boolean
}

export type DisposeAuthBackground = () => void

const RESIZE_DELAY = 150
const MOBILE_FRAME_INTERVAL = 1000 / 30
const MOBILE_DPR_CAP = 1.5
const DESKTOP_DPR_CAP = 2

/** 无 Canvas / 取色失败时返回 noop，保留 .auth-shell 的 CSS 渐变（I5） */
const noop: DisposeAuthBackground = () => {}

export function mountAuthBackground(
  canvas: HTMLCanvasElement,
  options: MountAuthBackgroundOptions,
): DisposeAuthBackground {
  const ctx = canvas.getContext('2d')
  if (!ctx) return noop
  const context2d: CanvasRenderingContext2D = ctx

  const palette = readPalette()
  if (!palette) return noop
  const colors: Palette = palette

  const variant = createFlowField(options.isMobile)
  const pointer = { x: 0, y: 0 }
  const frameInterval = options.isMobile ? MOBILE_FRAME_INTERVAL : 0

  let width = 0
  let height = 0
  let rafId: number | null = null
  let resizeTimer: ReturnType<typeof setTimeout> | undefined
  let lastFrame = 0
  let disposed = false

  function context(): FrameContext {
    return {
      ctx: context2d,
      width,
      height,
      palette: colors,
      isMobile: options.isMobile,
      pointer,
    }
  }

  function layout() {
    const rect = canvas.getBoundingClientRect()
    width = Math.max(0, Math.round(rect.width))
    height = Math.max(0, Math.round(rect.height))
    if (!width || !height) return

    const dprCap = options.isMobile ? MOBILE_DPR_CAP : DESKTOP_DPR_CAP
    const dpr = Math.min(window.devicePixelRatio || 1, dprCap)
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
    context2d.setTransform(dpr, 0, 0, dpr, 0, 0)
    try {
      variant.resize(context())
    } catch {
      stop()
    }
  }

  function draw(timeMs: number) {
    if (disposed || !width || !height) return
    try {
      variant.frame(context(), timeMs)
    } catch {
      // 绘制失败不能冒泡到 React；停止循环后画布保持透明，CSS 渐变自然兜底
      stop()
    }
  }

  function loop(timeMs: number) {
    if (disposed) return
    if (!frameInterval || timeMs - lastFrame >= frameInterval) {
      lastFrame = timeMs
      draw(timeMs)
    }
    rafId = window.requestAnimationFrame(loop)
  }

  function start() {
    if (disposed || options.reducedMotion || rafId !== null || document.hidden) return
    lastFrame = 0
    rafId = window.requestAnimationFrame(loop)
  }

  function stop() {
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  function onVisibilityChange() {
    if (document.hidden) {
      stop()
      return
    }
    draw(window.performance.now())
    start()
  }

  function onResize() {
    if (resizeTimer !== undefined) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => {
      resizeTimer = undefined
      layout()
      if (options.reducedMotion) draw(0)
    }, RESIZE_DELAY)
  }

  function onPointerMove(event: PointerEvent) {
    const vw = window.innerWidth || 1
    const vh = window.innerHeight || 1
    pointer.x = Math.max(-1, Math.min(1, (event.clientX / vw) * 2 - 1))
    pointer.y = Math.max(-1, Math.min(1, (event.clientY / vh) * 2 - 1))
  }

  layout()
  draw(0)
  start()

  window.addEventListener('resize', onResize, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)
  if (!options.isMobile && !options.reducedMotion) {
    window.addEventListener('pointermove', onPointerMove, { passive: true })
  }

  return () => {
    if (disposed) return
    disposed = true
    stop()
    if (resizeTimer !== undefined) {
      clearTimeout(resizeTimer)
      resizeTimer = undefined
    }
    window.removeEventListener('resize', onResize)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    window.removeEventListener('pointermove', onPointerMove)
  }
}

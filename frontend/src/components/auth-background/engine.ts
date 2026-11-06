/** 认证页背景引擎：唯一生命周期入口（ADR 0016 §2 / I2 / I4）.
 *
 * 职责：一次性静态绘制、DPR 与尺寸、resize 节流重绘、dispose。
 * 不启动 rAF、不监听可见性 / 指针：晶格是固定背景图，页面空闲时零持续开销。
 */

import { drawLattice } from './lattice'
import { readPalette } from './palette'

export interface MountAuthBackgroundOptions {
  isMobile: boolean
}

export type DisposeAuthBackground = () => void

const RESIZE_DELAY = 150
const MOBILE_DPR_CAP = 1.5
const DESKTOP_DPR_CAP = 2

/** 无 Canvas / 取色失败时返回 noop，保留 .auth-shell 的 CSS 渐变（I4） */
const noop: DisposeAuthBackground = () => {}

export function mountAuthBackground(
  canvas: HTMLCanvasElement,
  options: MountAuthBackgroundOptions,
): DisposeAuthBackground {
  const maybeCtx = canvas.getContext('2d')
  if (!maybeCtx) return noop
  const ctx = maybeCtx

  const maybePalette = readPalette()
  if (!maybePalette) return noop
  const palette = maybePalette

  let resizeTimer: ReturnType<typeof setTimeout> | undefined
  let disposed = false

  function layout() {
    const rect = canvas.getBoundingClientRect()
    const width = Math.max(0, Math.round(rect.width))
    const height = Math.max(0, Math.round(rect.height))
    if (!width || !height) return

    const dprCap = options.isMobile ? MOBILE_DPR_CAP : DESKTOP_DPR_CAP
    const dpr = Math.min(window.devicePixelRatio || 1, dprCap)
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)

    try {
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      drawLattice({
        ctx,
        width: canvas.width,
        height: canvas.height,
        dpr,
        palette,
        isMobile: options.isMobile,
      })
    } catch {
      // 绘制失败不能冒泡到 React；画布保持透明，CSS 渐变自然兜底
      canvas.width = 0
      canvas.height = 0
    }
  }

  function onResize() {
    if (resizeTimer !== undefined) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => {
      resizeTimer = undefined
      if (!disposed) layout()
    }, RESIZE_DELAY)
  }

  layout()
  window.addEventListener('resize', onResize, { passive: true })

  return () => {
    if (disposed) return
    disposed = true
    if (resizeTimer !== undefined) {
      clearTimeout(resizeTimer)
      resizeTimer = undefined
    }
    window.removeEventListener('resize', onResize)
  }
}

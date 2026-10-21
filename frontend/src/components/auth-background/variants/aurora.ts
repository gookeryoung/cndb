/** 极光流光：多正弦叠加的带状光幕，纵向渐变衰减（ADR 0014 D2） */

import { withAlpha } from '../palette'
import type { BackgroundVariant } from '../types'

interface Band {
  base: number
  amplitude: number
  frequency: number
  speed: number
  phase: number
  alpha: number
}

const BANDS: Band[] = [
  { base: 0.2, amplitude: 0.06, frequency: 0.0055, speed: 0.00022, phase: 0, alpha: 0.24 },
  { base: 0.31, amplitude: 0.05, frequency: 0.0072, speed: -0.00018, phase: 1.7, alpha: 0.18 },
  { base: 0.42, amplitude: 0.065, frequency: 0.0048, speed: 0.00015, phase: 3.1, alpha: 0.15 },
  { base: 0.55, amplitude: 0.04, frequency: 0.0085, speed: -0.00024, phase: 4.4, alpha: 0.11 },
]

export function createAurora(isMobile: boolean): BackgroundVariant {
  let width = 0
  let height = 0
  const bands = isMobile ? BANDS.slice(0, 3) : BANDS

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) {
        width = c.width
        height = c.height
      }
    },

    frame(c, timeMs) {
      if (!width || !height) return
      const { ctx } = c
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = isMobile ? 'source-over' : c.isDark ? 'lighter' : 'source-over'
      ctx.clearRect(0, 0, width, height)

      const step = Math.max(8, width / 72)
      const pointerShift = isMobile ? 0 : c.pointer.y * 10

      for (const band of bands) {
        const points: Array<[number, number]> = []
        let top = height
        for (let x = 0; x <= width + step; x += step) {
          const wave =
            Math.sin(x * band.frequency + timeMs * band.speed + band.phase) * band.amplitude +
            Math.sin(x * band.frequency * 2.4 - timeMs * band.speed * 0.7 + band.phase) *
              band.amplitude *
              0.4
          const y = height * (band.base + wave) + pointerShift
          top = Math.min(top, y)
          points.push([x, y])
        }

        const gradient = ctx.createLinearGradient(0, top, 0, height * 0.92)
        gradient.addColorStop(0, withAlpha(c.palette.brand, band.alpha * (c.isDark ? 1 : 0.8)))
        gradient.addColorStop(0.35, withAlpha(c.palette.brand, band.alpha * 0.45))
        gradient.addColorStop(1, withAlpha(c.palette.brand, 0))

        ctx.beginPath()
        ctx.moveTo(points[0][0], points[0][1])
        for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1])
        ctx.lineTo(width, height)
        ctx.lineTo(0, height)
        ctx.closePath()
        ctx.fillStyle = gradient
        ctx.fill()

        ctx.beginPath()
        ctx.moveTo(points[0][0], points[0][1])
        for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1])
        ctx.lineWidth = 1
        ctx.strokeStyle = withAlpha(c.palette.brand, band.alpha * 0.9)
        ctx.stroke()
      }

      ctx.globalCompositeOperation = 'source-over'
    },
  }
}

/** 光点流体：少量大尺寸柔光圆斑慢速游移，形成 bokeh 式氛围（ADR 0014 D2） */

import { createRandom, withAlpha } from '../palette'
import type { BackgroundVariant } from '../types'

interface Orb {
  xRatio: number
  yRatio: number
  radiusRatio: number
  speed: number
  phaseX: number
  phaseY: number
  strong: boolean
}

export function createOrbs(isMobile: boolean): BackgroundVariant {
  const random = createRandom(4409)
  let width = 0
  let height = 0
  let orbs: Orb[] = []

  function rebuild(w: number, h: number) {
    width = w
    height = h
    const count = isMobile ? 5 : 8
    orbs = Array.from({ length: count }, () => ({
      xRatio: 0.12 + random() * 0.76,
      yRatio: 0.12 + random() * 0.76,
      radiusRatio: 0.12 + random() * 0.24,
      speed: 0.00006 + random() * 0.00014,
      phaseX: random() * Math.PI * 2,
      phaseY: random() * Math.PI * 2,
      strong: random() < 0.4,
    }))
  }

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) rebuild(c.width, c.height)
    },

    frame(c, timeMs) {
      if (!width || !height || orbs.length === 0) return
      const { ctx } = c
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, width, height)
      if (c.isDark) ctx.globalCompositeOperation = 'lighter'

      const shortSide = Math.min(width, height)
      const pointerX = isMobile ? 0 : c.pointer.x * 10
      const pointerY = isMobile ? 0 : c.pointer.y * 10

      for (const orb of orbs) {
        const x =
          width * (orb.xRatio + Math.sin(timeMs * orb.speed + orb.phaseX) * 0.05) + pointerX
        const y =
          height * (orb.yRatio + Math.cos(timeMs * orb.speed * 0.8 + orb.phaseY) * 0.045) + pointerY
        const radius = shortSide * orb.radiusRatio * (0.9 + 0.1 * Math.sin(timeMs * 0.0003 + orb.phaseX))

        if (radius <= 0) continue
        const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
        const strength = c.isDark ? 0.22 : 0.13
        gradient.addColorStop(0, withAlpha(c.palette.brand, strength * (orb.strong ? 1 : 0.7)))
        gradient.addColorStop(0.55, withAlpha(c.palette.brand, strength * 0.35))
        gradient.addColorStop(1, withAlpha(c.palette.brand, 0))
        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(x, y, radius, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.globalCompositeOperation = 'source-over'
    },
  }
}

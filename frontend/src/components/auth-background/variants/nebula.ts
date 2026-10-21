/** 星云漩涡：核心辉光 + 螺旋星尘，深色主题叠加发光（ADR 0016 D2 / D7） */

import { createRandom, particleBudget, withAlpha } from '../palette'
import type { BackgroundVariant } from '../types'

interface Dust {
  radius: number
  angle: number
  speed: number
  size: number
  phase: number
  accent: boolean
}

export function createNebula(isMobile: boolean): BackgroundVariant {
  const random = createRandom(2207)
  let width = 0
  let height = 0
  let dust: Dust[] = []
  let maxRadius = 0

  function rebuild(w: number, h: number) {
    width = w
    height = h
    maxRadius = Math.min(w, h) * 0.46
    const count = particleBudget(w * h, isMobile ? 70 : 180, isMobile, 11000)
    dust = Array.from({ length: count }, () => ({
      radius: Math.pow(random(), 0.65) * maxRadius,
      angle: random() * Math.PI * 2,
      speed: 0.00004 + random() * 0.00016,
      size: 0.6 + random() * 2.4,
      phase: random() * Math.PI * 2,
      accent: random() < 0.22,
    }))
  }

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) rebuild(c.width, c.height)
    },

    frame(c, timeMs) {
      if (!width || !height || dust.length === 0) return
      const { ctx } = c
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, width, height)

      const centerX = width * 0.5 + (isMobile ? 0 : c.pointer.x * 12)
      const centerY = height * 0.45 + (isMobile ? 0 : c.pointer.y * 12)

      const glow = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, maxRadius)
      glow.addColorStop(0, withAlpha(c.palette.brand, c.isDark ? 0.2 : 0.1))
      glow.addColorStop(0.45, withAlpha(c.palette.brand, c.isDark ? 0.06 : 0.04))
      glow.addColorStop(1, withAlpha(c.palette.brand, 0))
      ctx.fillStyle = glow
      ctx.fillRect(0, 0, width, height)

      if (c.isDark) ctx.globalCompositeOperation = 'lighter'

      for (const particle of dust) {
        const angle = particle.angle + timeMs * particle.speed
        const breath = 0.78 + 0.22 * Math.sin(timeMs * 0.00018 + particle.phase)
        const radius = particle.radius * breath
        const x = centerX + Math.cos(angle) * radius
        const y = centerY + Math.sin(angle) * radius * 0.74
        const depth = 1 - particle.radius / (maxRadius * 1.15)
        const alpha =
          (c.isDark ? 0.34 : 0.2) * depth * (0.55 + 0.45 * Math.sin(timeMs * 0.001 + particle.phase))
        ctx.fillStyle = withAlpha(particle.accent ? c.palette.brand : c.palette.text, alpha)
        ctx.beginPath()
        ctx.arc(x, y, particle.size, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.globalCompositeOperation = 'source-over'
    },
  }
}

/** 星座连线：星点缓慢漂移 + 近邻连线 + 品牌色高亮星（ADR 0016 D2） */

import { createRandom, particleBudget, withAlpha } from '../palette'
import type { BackgroundVariant } from '../types'

interface Star {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  phase: number
  accent: boolean
}

export function createConstellation(isMobile: boolean): BackgroundVariant {
  const random = createRandom(1103)
  let width = 0
  let height = 0
  let stars: Star[] = []
  let lastTime = 0

  function rebuild(w: number, h: number) {
    width = w
    height = h
    const count = particleBudget(w * h, isMobile ? 44 : 110, isMobile, 16000)
    stars = Array.from({ length: count }, () => ({
      x: random() * w,
      y: random() * h,
      vx: (random() - 0.5) * 5,
      vy: (random() - 0.5) * 5,
      radius: 0.7 + random() * 1.3,
      phase: random() * Math.PI * 2,
      accent: random() < 0.18,
    }))
    lastTime = 0
  }

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) rebuild(c.width, c.height)
    },

    frame(c, timeMs) {
      if (!width || !height || stars.length === 0) return
      const { ctx } = c
      const delta = lastTime === 0 ? 0 : Math.min(48, Math.max(0, timeMs - lastTime))
      lastTime = timeMs

      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, width, height)

      const offsetX = isMobile ? 0 : c.pointer.x * 8
      const offsetY = isMobile ? 0 : c.pointer.y * 8

      for (const star of stars) {
        star.x += star.vx * delta * 0.001
        star.y += star.vy * delta * 0.001
        if (star.x < -20) star.x = width + 20
        else if (star.x > width + 20) star.x = -20
        if (star.y < -20) star.y = height + 20
        else if (star.y > height + 20) star.y = -20
      }

      const maxDistance = Math.min(width, height) * (isMobile ? 0.24 : 0.17)
      const maxDistanceSq = maxDistance * maxDistance
      ctx.lineWidth = 0.6

      for (let i = 0; i < stars.length; i++) {
        const a = stars[i]
        for (let j = i + 1; j < stars.length; j++) {
          const b = stars[j]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const distanceSq = dx * dx + dy * dy
          if (distanceSq > maxDistanceSq) continue
          const alpha = (1 - Math.sqrt(distanceSq) / maxDistance) * 0.3
          ctx.strokeStyle = withAlpha(c.palette.brand, alpha)
          ctx.beginPath()
          ctx.moveTo(a.x + offsetX, a.y + offsetY)
          ctx.lineTo(b.x + offsetX, b.y + offsetY)
          ctx.stroke()
        }
      }

      for (const star of stars) {
        const twinkle = 0.55 + 0.35 * Math.sin(timeMs * 0.0012 + star.phase)
        ctx.fillStyle = withAlpha(star.accent ? c.palette.brand : c.palette.text, twinkle * 0.65)
        ctx.beginPath()
        ctx.arc(star.x + offsetX, star.y + offsetY, star.radius, 0, Math.PI * 2)
        ctx.fill()
      }
    },
  }
}

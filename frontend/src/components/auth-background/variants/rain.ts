/** 数字雨：字符列下落 + 逐级衰减拖尾，不填充底色以保留 CSS 渐变（ADR 0016 D2） */

import { TEXT } from '@/theme/tokens'

import { createRandom, withAlpha } from '../palette'
import type { BackgroundVariant } from '../types'

const GLYPHS = '01ABCDEF<>[]{}/\\|=+-*#$%&'

interface Column {
  x: number
  speed: number
  offset: number
  trail: number
  seed: number
}

export function createRain(isMobile: boolean): BackgroundVariant {
  const random = createRandom(3301)
  const fontSize = isMobile ? TEXT['2xs'] : TEXT.xs
  let width = 0
  let height = 0
  let columns: Column[] = []

  function rebuild(w: number, h: number) {
    width = w
    height = h
    const gap = isMobile ? 22 : 16
    const count = Math.max(8, Math.floor(w / gap))
    columns = Array.from({ length: count }, (_, index) => ({
      x: (index + 0.5) * gap,
      speed: 0.08 + random() * 0.14,
      offset: random() * (h + 240),
      trail: 6 + Math.floor(random() * (isMobile ? 8 : 13)),
      seed: Math.floor(random() * 1000),
    }))
  }

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) rebuild(c.width, c.height)
    },

    frame(c, timeMs) {
      if (!width || !height || columns.length === 0) return
      const { ctx } = c
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, width, height)

      const offsetX = isMobile ? 0 : c.pointer.x * 6
      const tick = Math.floor(timeMs / 120)
      ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`
      ctx.textBaseline = 'top'

      for (const column of columns) {
        const span = height + column.trail * fontSize
        const head = (timeMs * column.speed + column.offset) % span

        for (let k = 0; k < column.trail; k++) {
          const y = head - k * fontSize
          if (y < -fontSize || y > height) continue
          const fade = (1 - k / column.trail) * (c.isDark ? 0.55 : 0.34)
          ctx.fillStyle = withAlpha(k === 0 ? c.palette.brand : c.palette.text, fade)
          const glyph = GLYPHS[(column.seed + k * 7 + tick) % GLYPHS.length]
          ctx.fillText(glyph, column.x + offsetX, y)
        }
      }
    },
  }
}

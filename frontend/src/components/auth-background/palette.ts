/** 取色与绘制小工具（ADR 0016 D7）.
 *
 * 画布颜色必须来自 `--cn-*` 主题变量：ThemeProvider 切换 body class 后，
 * 组件以新色板重建引擎，避免在 JS 里维护 10 套硬编码配色。
 */

import type { Palette } from './types'

const HEX_PATTERN = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i
const RGB_PATTERN =
  /^rgba?\(\s*([\d.]+)\s*[,\s]\s*([\d.]+)\s*[,\s]\s*([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i

function parseHex(value: string): [number, number, number] | null {
  const match = value.match(HEX_PATTERN)
  if (!match) return null
  let hex = match[1]
  if (hex.length === 3 || hex.length === 4) {
    hex = hex
      .slice(0, 3)
      .split('')
      .map(ch => ch + ch)
      .join('')
  }
  const r = Number.parseInt(hex.slice(0, 2), 16)
  const g = Number.parseInt(hex.slice(2, 4), 16)
  const b = Number.parseInt(hex.slice(4, 6), 16)
  return Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b) ? [r, g, b] : null
}

/** #rgb / #rrggbb / rgb() / rgba() → 带目标透明度的 rgba()；无法解析时原样返回 */
export function withAlpha(color: string, alpha: number): string {
  const value = color.trim()
  const a = Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 0

  const hex = parseHex(value)
  if (hex) return `rgba(${hex[0]}, ${hex[1]}, ${hex[2]}, ${a})`

  const rgb = value.match(RGB_PATTERN)
  if (rgb) {
    const r = Math.round(Number(rgb[1]))
    const g = Math.round(Number(rgb[2]))
    const b = Math.round(Number(rgb[3]))
    return `rgba(${r}, ${g}, ${b}, ${a})`
  }

  return value
}

/** 读取主题色板；三个变量任一缺失即视为失败，由 CSS 渐变兜底（ADR 0016 I5） */
export function readPalette(): Palette | null {
  if (typeof window === 'undefined' || !document.body) return null
  const style = getComputedStyle(document.body)
  const brand = style.getPropertyValue('--cn-brand-color').trim()
  const text = style.getPropertyValue('--cn-text-primary').trim()
  const bg = style.getPropertyValue('--cn-bg-page').trim()
  if (!brand || !text || !bg) return null
  return { brand, text, bg }
}

/** 固定种子的伪随机（mulberry32）：同一变体每次挂载形态稳定，测试可复现 */
export function createRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let value = Math.imul(state ^ (state >>> 15), 1 | state)
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

/** 按视口面积给粒子数设上限；移动端整体再降一档（ADR 0016 D6） */
export function particleBudget(
  area: number,
  max: number,
  isMobile: boolean,
  perPixel = 14000,
): number {
  const base = Math.min(max, Math.max(16, Math.round(area / perPixel)))
  return isMobile ? Math.max(10, Math.round(base * 0.45)) : base
}

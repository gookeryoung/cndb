/** 取色与绘制小工具（ADR 0016 D7）.
 *
 * 认证页是固定深色舞台：颜色来自独立 `--cn-auth-*` token（定义在 index.css 的
 * `:root` 固定舞台块），不随 10 套主题变化。这样浅色主题的品牌色（如 minimal 深灰）
 * 不会在黑底上失去对比度；青紫渐变取 accent / accent-alt 两端。
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

/** 读取固定舞台色板；三个 auth token 任一缺失即视为失败，由 CSS 背景兜底（ADR 0016 I5） */
export function readPalette(): Palette | null {
  if (typeof window === 'undefined' || !document.body) return null
  const style = getComputedStyle(document.body)
  const accent = style.getPropertyValue('--cn-auth-accent').trim()
  const accentAlt = style.getPropertyValue('--cn-auth-accent-alt').trim()
  const ink = style.getPropertyValue('--cn-auth-ink').trim()
  if (!accent || !accentAlt || !ink) return null
  return { accent, accentAlt, ink }
}

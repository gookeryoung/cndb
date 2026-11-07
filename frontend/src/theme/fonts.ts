/** 字体设置：字号档位与全局加粗的元信息、默认值与 localStorage 持久化. */

import { TEXT } from './tokens'

/* ─────────────── 字体设置（字号 / 加粗） ─────────────── */

/** 字号档位：小 / 标准 / 大 / 特大 */
export const FONT_SCALES = ['small', 'standard', 'large', 'huge'] as const
export type FontScale = (typeof FONT_SCALES)[number]

export interface FontScaleMeta {
  id: FontScale
  label: string
  /** 该档位对应的基础字号（px），注入 antd token.fontSize 与 body */
  px: number
}

export const FONT_SCALE_META: Record<FontScale, FontScaleMeta> = {
  small: { id: 'small', label: '小', px: 12 },
  standard: { id: 'standard', label: '标准', px: 14 },
  large: { id: 'large', label: '大', px: 16 },
  huge: { id: 'huge', label: '特大', px: 18 },
}

/** 全局字号档位对应的 t-shirt 字号变量 —— 设置档位时由 ThemeProvider 写到 :root.
 *
 * 背景：index.css / 组件内的 `--cn-text-*` 是固定 px，只改 body / antd token 时
 * 大量显式写了字号的元素不会跟随。这里按档位基准（standard=14px）等比缩放全部
 * `--cn-text-*`，保留字号的相对层级（正文 / 辅助文字 / 标题一起放大）。
 */
export function resolveTextVars(scale: FontScale): Record<string, string> {
  const factor = FONT_SCALE_META[scale].px / FONT_SCALE_META.standard.px
  const out: Record<string, string> = {}
  for (const [name, px] of Object.entries(TEXT)) {
    // 保留一位小数：小档位下 10px 一档仍有可读性，避免四舍五入后相邻档位并档
    const scaled = Math.max(9, Math.round(px * factor * 10) / 10)
    out[`--cn-text-${name}`] = `${scaled}px`
  }
  return out
}

export interface FontSettings {
  /** 基础字号档位 */
  scale: FontScale
  /** 全局加粗强调 */
  bold: boolean
}

export const DEFAULT_FONT_SETTINGS: FontSettings = { scale: 'standard', bold: false }

const FONT_KEY = 'cndb_font'

export function loadFontSettings(): FontSettings {
  try {
    const raw = localStorage.getItem(FONT_KEY)
    if (!raw) return { ...DEFAULT_FONT_SETTINGS }
    const parsed = JSON.parse(raw) as Partial<FontSettings>
    // 非法档位回退默认，避免持久化脏数据导致渲染异常
    const scale = FONT_SCALES.includes(parsed.scale as FontScale)
      ? (parsed.scale as FontScale)
      : DEFAULT_FONT_SETTINGS.scale
    const bold = typeof parsed.bold === 'boolean'
      ? parsed.bold
      : DEFAULT_FONT_SETTINGS.bold
    return { scale, bold }
  } catch { /* noop */ }
  return { ...DEFAULT_FONT_SETTINGS }
}

export function saveFontSettings(settings: FontSettings) {
  try { localStorage.setItem(FONT_KEY, JSON.stringify(settings)) } catch { /* noop */ }
}

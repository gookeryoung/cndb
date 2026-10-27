/**
 * 文档引用宽度（ADR 0051）：图表 / 数据表引用的显示宽度参数。
 *
 * 宽度只存在于正文占位符：`{{chart:<id>|width=N}}`、`{{table:<id>|…|width=N}}`，
 * 按引用出现位置独立。缺省、非整数、越界一律回退 {@link DEFAULT_REF_WIDTH}。
 * 本模块是宽度的唯一常量与改写入口（不依赖具体解析器，避免循环引用）。
 */

export const DEFAULT_REF_WIDTH = 75
export const MIN_REF_WIDTH = 25
export const MAX_REF_WIDTH = 100

export type RefKind = 'chart' | 'table'

/** 宽度调整事件：按 kind + 目标 ID + 出现序号（0 基）定位唯一引用 */
export interface RefWidthChange {
  kind: RefKind
  id: number
  occurrence: number
  width: number
}

/** 解析宽度参数：缺省 / 非整数 / 越界 → 默认 75 */
export function parseRefWidth(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return DEFAULT_REF_WIDTH
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isInteger(n) || n < MIN_REF_WIDTH || n > MAX_REF_WIDTH) return DEFAULT_REF_WIDTH
  return n
}

/** 段落级占位符（含可选参数），与 chartRef.ts / tableRef.ts 语法一致 */
const REF_RE = /^\{\{(chart|table):(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$/

/**
 * 按出现序号改写一个引用的 `width` 参数；未命中原样返回。
 *
 * - 已有 `width` 时替换，没有则追加到参数末尾；其余参数顺序与内容保持不变；
 * - 段内首尾空白、段落分隔符都保留，返回整篇正文。
 */
export function rewriteRefWidth(content: string, change: RefWidthChange): string {
  if (!content) return content
  const parts = content.split(/(\n\n+)/)
  let occurrence = -1

  for (let i = 0; i < parts.length; i += 2) {
    const part = parts[i]
    if (!part) continue
    const trimmed = part.trim()
    const m = REF_RE.exec(trimmed)
    if (!m || m[1] !== change.kind || Number(m[2]) !== change.id) continue
    occurrence += 1
    if (occurrence !== change.occurrence) continue

    const params = (m[3] ? m[3].slice(1).split('|') : []).filter(p => p && !/^width=/.test(p))
    const width = parseRefWidth(change.width)
    const rebuilt = `{{${change.kind}:${m[2]}${[...params, `width=${width}`].map(p => `|${p}`).join('')}}}`
    const start = part.indexOf(trimmed)
    parts[i] = part.slice(0, start) + rebuilt + part.slice(start + trimmed.length)
    break
  }

  return parts.join('')
}

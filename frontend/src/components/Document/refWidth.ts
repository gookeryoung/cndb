/**
 * 文档引用宽度（ADR 0051 / 0052）：数据表引用的显示宽度参数。
 *
 * 数据表宽度在正文占位符 `{{table:<id>|…|width=N}}`；图表宽度已移入正文内嵌块
 * （`chartBlock.ts` 的 `width` 字段）。缺省、非整数、越界一律回退
 * {@link DEFAULT_REF_WIDTH}。本模块是宽度的唯一常量与归一入口。
 */

export const DEFAULT_REF_WIDTH = 75
export const MIN_REF_WIDTH = 25
export const MAX_REF_WIDTH = 100

export type RefKind = 'table'

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

/** 段落级数据表占位符（含可选参数），与 tableRef.ts 语法一致 */
const REF_RE = /^\{\{table:(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$/

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
    if (!m || Number(m[1]) !== change.id) continue
    occurrence += 1
    if (occurrence !== change.occurrence) continue

    const params = (m[2] ? m[2].slice(1).split('|') : []).filter(p => p && !/^width=/.test(p))
    const width = parseRefWidth(change.width)
    const rebuilt = `{{table:${m[1]}${[...params, `width=${width}`].map(p => `|${p}`).join('')}}}`
    const start = part.indexOf(trimmed)
    parts[i] = part.slice(0, start) + rebuilt + part.slice(start + trimmed.length)
    break
  }

  return parts.join('')
}

/**
 * 文档正文引用切片（ADR 0045 / 0052）：数据表占位符与图表内嵌块.
 *
 * 段落级判定：`` {{table:…}} `` 独占段落切为 table 片段，`` ```chart `` 围栏块独占
 * 段落切为 chart 片段，其余 Markdown 原样合并（含分隔空行）。
 */

import { parseChartBlock, type ChartBlock } from './chartBlock'
import { parseTableRef, type TableRef } from './tableRef'

/** Markdown 内容切片：普通片段 / 数据表引用 / 图表块 */
export type RefsContentSegment =
  | { type: 'md'; text: string }
  | { type: 'table'; ref: TableRef }
  | { type: 'chart'; block: ChartBlock }

/**
 * 按段落切片。
 *
 * `opts.chartsOnly`：只切图表块，`{{table:…}}` 留在 md 文本里 ——
 * 游客分享页（ADR 0017 / 0052 D10）只免登录渲染图表。
 */
export function splitRefs(content: string, opts?: { chartsOnly?: boolean }): RefsContentSegment[] {
  if (!content) return []
  const parts = content.split(/(\n\n+)/)
  const segments: RefsContentSegment[] = []
  let mdBuf = ''

  const flushMd = () => {
    if (mdBuf) {
      segments.push({ type: 'md', text: mdBuf })
      mdBuf = ''
    }
  }

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    if (!part) continue
    if (i % 2 === 1) {
      if (mdBuf) mdBuf += part
      continue
    }
    if (!opts?.chartsOnly) {
      const ref = parseTableRef(part)
      if (ref) {
        flushMd()
        segments.push({ type: 'table', ref })
        continue
      }
    }
    const block = parseChartBlock(part)
    if (block) {
      flushMd()
      segments.push({ type: 'chart', block })
      continue
    }
    mdBuf += part
  }
  flushMd()
  return segments
}

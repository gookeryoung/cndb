/**
 * 数据表动态引用占位语法解析（纯函数）。
 *
 * 语法：`{{table:<表ID>}}`，可选参数以 `|` 分隔：
 * - `view=<视图ID>`：按视图的 filters/sortings 拉取行
 * - `limit=<每页行数>`：上限 {@link MAX_TABLE_REF_LIMIT}，非法回退默认值
 * - `width=<显示宽度百分比>`：25–100，显式指定但非法回退 75；缺省时由渲染端
 *   回退到个人设置的表格默认宽度（ADR 0051）
 *
 * 占位符须独占一个段落（前后空行分隔，段内无其他文本）才被解析；
 * 行内混排视为普通 Markdown 文本。
 */

import { parseRefWidth } from './refWidth'

/** 每页行数上限（与设计约定一致，防止引用拖垮预览） */
export const MAX_TABLE_REF_LIMIT = 50

/** 未指定 limit 时的默认每页行数 */
export const DEFAULT_TABLE_REF_LIMIT = 20

/** 解析后的数据表引用 */
export interface TableRef {
  /** 目标表 ID */
  tableId: number
  /** 视图 ID（可选，按视图过滤/排序拉取） */
  view?: number
  /** 每页行数（已钳制到 [1, MAX_TABLE_REF_LIMIT]） */
  limit: number
  /** 显示宽度百分比（25–100）；未显式指定 width 参数时为 undefined，
   *  由渲染端回退到个人设置（文档页签）的表格默认宽度；显式指定但非法时回退 75 */
  width?: number
}

/** Markdown 内容切片：普通片段 / 数据表引用片段 */
export type ContentSegment =
  | { type: 'md'; text: string }
  | { type: 'table'; ref: TableRef }

/** 段落级占位符：整段仅含一个 `{{table:…}}`（参数键限字母，值限非分隔符字符） */
const TABLE_REF_RE = /^\{\{table:(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$/

/** 单个参数 `key=value` */
const PARAM_RE = /^([a-zA-Z]+)=(.*)$/

/**
 * 解析一行占位符文本为 TableRef；不合法返回 null。
 *
 * 未知参数键忽略；limit 非法/越界回退或钳制；view 非数字忽略。
 */
export function parseTableRef(line: string): TableRef | null {
  const trimmed = line.trim()
  const m = TABLE_REF_RE.exec(trimmed)
  if (!m) return null

  const ref: TableRef = {
    tableId: Number(m[1]),
    limit: DEFAULT_TABLE_REF_LIMIT,
  }

  const paramsRaw = m[2]
  if (paramsRaw) {
    // 去掉首个 "|" 后逐段解析
    for (const part of paramsRaw.slice(1).split('|')) {
      const pm = PARAM_RE.exec(part)
      if (!pm) continue
      const [, key, value] = pm
      if (key === 'limit') {
        const n = Number(value)
        if (Number.isFinite(n) && n >= 1) {
          ref.limit = Math.min(Math.floor(n), MAX_TABLE_REF_LIMIT)
        }
      } else if (key === 'view') {
        const n = Number(value)
        if (Number.isFinite(n) && n >= 1) ref.view = Math.floor(n)
      } else if (key === 'width') {
        ref.width = parseRefWidth(value)
      }
    }
  }
  return ref
}

/**
 * 将 Markdown 内容按段落切片：独占段落的 `{{table:…}}` 切为 table 片段，
 * 其余（含分隔空行）合并为相邻 md 片段，保持原文语义不变。
 */
export function splitTableRefs(content: string): ContentSegment[] {
  if (!content) return []

  // 按空行分段，保留分隔符：奇数索引为 "\n\n+"，偶数索引为段落
  const parts = content.split(/(\n\n+)/)
  const segments: ContentSegment[] = []
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
      // 段落分隔符：仅当已有 md 内容时并入（纯引用之间的空行不产生空 md 片段）
      if (mdBuf) mdBuf += part
      continue
    }
    const ref = parseTableRef(part)
    if (ref) {
      flushMd()
      segments.push({ type: 'table', ref })
    } else {
      mdBuf += part
    }
  }
  flushMd()
  return segments
}

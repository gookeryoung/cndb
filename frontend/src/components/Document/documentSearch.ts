/** 文档查找 / 替换 —— 纯函数层.
 *
 * 与编辑器解耦：输入正文与查询串，输出匹配区间 / 新正文 / 新光标位置。
 * 说明：面向纯 textarea 的编辑器，高亮由「选中当前匹配」表达（无法给 textarea 内部染色）。
 */

export interface MatchRange {
  /** 匹配起点（含） */
  start: number
  /** 匹配终点（不含） */
  end: number
}

export interface FindOptions {
  /** 是否区分大小写（默认 false，即不区分） */
  caseSensitive?: boolean
}

/** 在正文中查找全部**不重叠**匹配（从左到右），空查询返回空数组 */
export function findMatches(value: string, query: string, options: FindOptions = {}): MatchRange[] {
  if (!query) return []
  const hay = options.caseSensitive ? value : value.toLowerCase()
  const needle = options.caseSensitive ? query : query.toLowerCase()
  const out: MatchRange[] = []
  let idx = hay.indexOf(needle)
  while (idx !== -1) {
    out.push({ start: idx, end: idx + query.length })
    idx = hay.indexOf(needle, idx + needle.length)
  }
  return out
}

/** 当前应选中的匹配下标：从光标处向后/向前找第一个匹配，越界时环绕；无匹配返回 -1 */
export function nextMatchIndex(matches: MatchRange[], caret: number, direction: 1 | -1 = 1): number {
  if (matches.length === 0) return -1
  const pos = Math.max(0, caret)
  if (direction === 1) {
    const found = matches.findIndex(m => m.start >= pos)
    return found === -1 ? 0 : found
  }
  for (let i = matches.length - 1; i >= 0; i--) {
    if (matches[i]!.end <= pos) return i
  }
  return matches.length - 1
}

/** 替换单个匹配，返回新正文与替换后光标位置（光标落在替换文本之后） */
export function replaceMatch(value: string, match: MatchRange, replacement: string): { value: string; caret: number } {
  const next = value.slice(0, match.start) + replacement + value.slice(match.end)
  return { value: next, caret: match.start + replacement.length }
}

/** 全部替换（字面量替换，不解释 $1 之类反向引用），返回新正文与替换处数 */
export function replaceAllMatches(
  value: string,
  query: string,
  replacement: string,
  options: FindOptions = {},
): { value: string; count: number } {
  const matches = findMatches(value, query, options)
  if (matches.length === 0) return { value, count: 0 }
  let out = ''
  let cursor = 0
  for (const m of matches) {
    out += value.slice(cursor, m.start) + replacement
    cursor = m.end
  }
  out += value.slice(cursor)
  return { value: out, count: matches.length }
}

/** 在当前匹配区间附近统计「第几处 / 共几处」（用于计数展示） */
export function matchOrdinal(matches: MatchRange[], caret: number): number {
  const idx = matches.findIndex(m => m.start <= caret && caret < m.end)
  return idx === -1 ? -1 : idx
}

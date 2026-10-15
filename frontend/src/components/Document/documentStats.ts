/** 文档正文统计 —— 纯函数层.
 *
 * 面向中文 Markdown：中文没有分词边界，故用「字符数 + 段落数 + 行数」表达体量，
 * 阅读时长按常见中文阅读速度 300 字/分钟估算（仅作参考）。
 */

export interface DocumentStats {
  /** 字符总数（含空白与换行） */
  chars: number
  /** 字符数（剔除所有空白字符） */
  charsNoSpace: number
  /** 行数（空文本记为 0 行） */
  lines: number
  /** 段落数（非空行数） */
  paragraphs: number
  /** 预计阅读分钟数（向上取整，空文本为 0） */
  readingMinutes: number
}

/** 中文阅读速度（字/分钟） */
export const READING_SPEED_CPM = 300

export function documentStats(text: string): DocumentStats {
  const value = text ?? ''
  const lines = value === '' ? 0 : value.split('\n').length
  const nonEmptyLines = value
    .split('\n')
    .filter(line => line.trim() !== '').length
  const charsNoSpace = value.replace(/\s/g, '').length
  return {
    chars: value.length,
    charsNoSpace,
    lines,
    paragraphs: nonEmptyLines,
    readingMinutes: charsNoSpace === 0 ? 0 : Math.ceil(charsNoSpace / READING_SPEED_CPM),
  }
}

/** 状态栏展示文案：`1,234 字 · 56 行 · 约 4 分钟` */
export function formatStatsLabel(stats: DocumentStats): string {
  const parts = [`${stats.chars.toLocaleString('zh-CN')} 字`, `${stats.lines} 行`]
  if (stats.readingMinutes > 0) parts.push(`约 ${stats.readingMinutes} 分钟`)
  return parts.join(' · ')
}

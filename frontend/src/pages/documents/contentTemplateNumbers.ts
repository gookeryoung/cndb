/**
 * 「去除标题序号」工具（ADR 0186 C6 / D7）.
 *
 * 编号权威归导出模板：正文自己写了「一、」「3.1」「第一章」时，导出会判定为显式
 * 序号并让模板编号失效。存量自定义内容模板不强制迁移，由用户主动使用本工具规范化，
 * 因此这里只做**纯文本**处理，不碰数据库（落库仍走用户的「保存」）。
 *
 * 口径与后端 `export/numbering.py::EXPLICIT_HEADING_PREFIX_RE` 对齐：
 * - 只处理 `##`…`######` 标题行（一级标题是文档标题，不动）；
 * - 只剥**行首**序号，标题里其余文字原样保留；
 * - 围栏代码块内不处理（围栏之间的示例文本属内容）。
 *
 * 注：JS 的 `\s` 已覆盖全角空格（U+3000），正则里不再写字面全角空格，
 * 以免触发 eslint `no-irregular-whitespace`。
 */

/** 标题行开头的显式序号（与后端同源口径） */
const HEADING_NUMBER_RE =
  /^\s*(?:第\s*[一二三四五六七八九十百千零〇两\d]+\s*[章节篇部]|[（(]\s*[一二三四五六七八九十百千零〇]+\s*[）)]|[一二三四五六七八九十百千零〇]+\s*[、.．]|\d+(?:[.．]\d+)+(?:\s*[、.．)）])?|\d+\s*[、.．)）])\s*/

const HEADING_LINE_RE = /^(#{2,6})(\s+)(.*)$/
const FENCE_RE = /^\s{0,3}(`{3,}|~{3,})/

export interface StripResult {
  text: string
  /** 被剥掉序号的标题行数（0 表示没变化） */
  changed: number
}

/** 剥掉 Markdown 标题行开头的显式序号 */
export function stripHeadingNumbers(markdown: string): StripResult {
  if (!markdown) return { text: markdown, changed: 0 }
  let fence: string | null = null
  let changed = 0
  const lines = markdown.split('\n').map(line => {
    const fenceMatch = FENCE_RE.exec(line)
    if (fenceMatch) {
      const marker = fenceMatch[1]
      if (fence == null) {
        fence = marker
      } else if (marker[0] === fence[0] && marker.length >= fence.length) {
        fence = null
      }
      return line
    }
    if (fence != null) return line
    const heading = HEADING_LINE_RE.exec(line)
    if (heading == null) return line
    const [, hashes, space, text] = heading
    const stripped = text.replace(HEADING_NUMBER_RE, '')
    if (stripped === text) return line
    if (stripped.trim() === '') return line // 整行只有序号，保留避免产生空标题
    changed += 1
    return `${hashes}${space}${stripped}`
  })
  return { text: lines.join('\n'), changed }
}

/** 供面板提示用：正文是否仍含带序号的标题 */
export function hasHeadingNumbers(markdown: string): boolean {
  return stripHeadingNumbers(markdown).changed > 0
}

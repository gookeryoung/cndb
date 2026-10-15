/** Markdown 编辑增强 —— 纯函数：在文本与选区上应用常见 Markdown 语法.
 *
 * 与编辑器解耦：输入 `(value, selectionStart, selectionEnd)`，输出新文本与新的选区，
 * 由调用方写回受控 state 并恢复光标。所有函数对空选区、越界选区、多行选区都安全。
 */

export interface MarkdownEditResult {
  /** 应用后的完整文本 */
  value: string
  /** 应用后应恢复的选区起点 */
  selectionStart: number
  /** 应用后应恢复的选区终点 */
  selectionEnd: number
}

/** 行首行内代码围栏标记 */
const CODE_FENCE = '```'

/** 选区越界与倒置归一化 */
function normalizeRange(value: string, start: number, end: number): [number, number] {
  const len = value.length
  const s = Math.max(0, Math.min(start, len))
  const e = Math.max(s, Math.min(end, len))
  return [s, e]
}

/** 选中文本两侧包裹（加粗 / 斜体 / 行内代码）；无选中时插入占位文本并选中它.
 *
 * 若选中内容已被同一对标记包裹，则视为「再次点击取消」（幂等切换）。
 */
export function wrapSelection(
  value: string,
  start: number,
  end: number,
  prefix: string,
  suffix: string = prefix,
  placeholder = '文本',
): MarkdownEditResult {
  const [s, e] = normalizeRange(value, start, end)
  const selected = value.slice(s, e)

  // 已包裹 → 取消（含选区包含标记本身，以及紧邻选区外侧即标记两种情形）
  const innerWrapped = selected.length >= prefix.length + suffix.length
    && selected.startsWith(prefix)
    && selected.endsWith(suffix)
  const outerWrapped = value.slice(s - prefix.length, s) === prefix && value.slice(e, e + suffix.length) === suffix
  if (innerWrapped) {
    const text = selected.slice(prefix.length, selected.length - suffix.length)
    const next = value.slice(0, s) + text + value.slice(e)
    return { value: next, selectionStart: s, selectionEnd: s + text.length }
  }
  if (outerWrapped) {
    const next = value.slice(0, s - prefix.length) + selected + value.slice(e + suffix.length)
    return { value: next, selectionStart: s - prefix.length, selectionEnd: e - prefix.length }
  }

  const text = selected || placeholder
  const next = value.slice(0, s) + prefix + text + suffix + value.slice(e)
  const selStart = s + prefix.length
  return { value: next, selectionStart: selStart, selectionEnd: selStart + text.length }
}

/** 把选区扩到完整行（可能跨多行），返回 [行首, 行尾] 偏移 */
function expandToLines(value: string, start: number, end: number): [number, number] {
  const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1
  const found = value.indexOf('\n', end)
  const lineEnd = found === -1 ? value.length : found
  return [lineStart, lineEnd]
}

/** 行前缀切换（无序列表 `- ` / 引用 `> `）：所选行全部带前缀则移除，否则补齐缺失行.
 *
 * 应用后选中整个受影响行块，便于连续操作（如再加一层引用）。
 */
export function toggleLinePrefix(value: string, start: number, end: number, prefix: string): MarkdownEditResult {
  const [s, e] = normalizeRange(value, start, end)
  const [lineStart, lineEnd] = expandToLines(value, s, e)
  const block = value.slice(lineStart, lineEnd)
  const lines = block.split('\n')
  const allHave = lines.every(line => line.startsWith(prefix))
  const next = lines
    .map(line => (allHave ? line.slice(prefix.length) : line.startsWith(prefix) ? line : prefix + line))
    .join('\n')
  return {
    value: value.slice(0, lineStart) + next + value.slice(lineEnd),
    selectionStart: lineStart,
    selectionEnd: lineStart + next.length,
  }
}

/** 有序列表 `1. 2. 3.`：全部已编号则移除，否则重新编号（保持既有顺序） */
export function toggleOrderedList(value: string, start: number, end: number): MarkdownEditResult {
  const [s, e] = normalizeRange(value, start, end)
  const [lineStart, lineEnd] = expandToLines(value, s, e)
  const block = value.slice(lineStart, lineEnd)
  const lines = block.split('\n')
  const orderedRe = /^\d+\.\s/
  const allHave = lines.every(line => orderedRe.test(line))
  const next = allHave
    ? lines.map(line => line.replace(orderedRe, '')).join('\n')
    : lines.map((line, i) => `${i + 1}. ${line.replace(orderedRe, '')}`).join('\n')
  return {
    value: value.slice(0, lineStart) + next + value.slice(lineEnd),
    selectionStart: lineStart,
    selectionEnd: lineStart + next.length,
  }
}

/** 标题：把所选行设为 `#`×level；若已是该级别则取消为普通段落（幂等切换） */
export function toggleHeading(value: string, start: number, end: number, level: number): MarkdownEditResult {
  const [s, e] = normalizeRange(value, start, end)
  const [lineStart, lineEnd] = expandToLines(value, s, e)
  const block = value.slice(lineStart, lineEnd)
  const headingRe = /^(#{1,6})\s+/
  const lines = block.split('\n')
  const prefix = `${'#'.repeat(Math.max(1, Math.min(6, level)))} `
  const allSameLevel = lines.every(line => {
    const m = headingRe.exec(line)
    return m !== null && m[1].length === level
  })
  const next = lines
    .map(line => (allSameLevel ? line.replace(headingRe, '') : prefix + line.replace(headingRe, '')))
    .join('\n')
  return {
    value: value.slice(0, lineStart) + next + value.slice(lineEnd),
    selectionStart: lineStart,
    selectionEnd: lineStart + next.length,
  }
}

/** 代码块：所选内容包裹在围栏中（独占行）；无选中时插入空代码块并把光标置于其中 */
export function wrapCodeBlock(
  value: string,
  start: number,
  end: number,
  language = '',
): MarkdownEditResult {
  const [s, e] = normalizeRange(value, start, end)
  const selected = value.slice(s, e)
  const lines = selected ? selected.split('\n') : []
  const body = lines.join('\n')
  const fence = `${CODE_FENCE}${language}`
  const needsLeadingBreak = s > 0 && value[s - 1] !== '\n'
  const needsTrailingBreak = e < value.length && value[e] !== '\n'
  const block = `${needsLeadingBreak ? '\n' : ''}${fence}\n${body}\n${CODE_FENCE}${needsTrailingBreak ? '\n' : ''}`
  const nextValue = value.slice(0, s) + block + value.slice(e)
  // 光标落在代码块正文起始处（空代码块时即围栏下一行行首）
  const bodyStart = s + (needsLeadingBreak ? 1 : 0) + fence.length + 1
  const bodyEnd = bodyStart + body.length
  return { value: nextValue, selectionStart: bodyStart, selectionEnd: bodyEnd }
}

/** 链接：有选中文本时作为链接文字，否则用占位文字；光标选中 URL 位置便于直接粘贴 */
export function insertLink(
  value: string,
  start: number,
  end: number,
  placeholder = '链接文字',
  url = 'https://',
): MarkdownEditResult {
  const [s, e] = normalizeRange(value, start, end)
  const selected = value.slice(s, e)
  const text = selected || placeholder
  const snippet = `[${text}](${url})`
  const next = value.slice(0, s) + snippet + value.slice(e)
  const urlStart = s + 1 + text.length + 2
  return { value: next, selectionStart: urlStart, selectionEnd: urlStart + url.length }
}

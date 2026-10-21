/** Markdown 表格（GFM）解析 — 把一行行源码还原成表头 / 对齐 / 数据行.
 *
 * 实时预览用：CodeMirror 里光标不在表格内时，把源码块换成真表格渲染；
 * 解析只管结构，单元格内的行内语法由调用方决定是否渲染。
 */

/** 单元格对齐（GFM 分隔行的 `:` 位置） */
export type MdTableAlign = 'left' | 'center' | 'right' | null

export interface MdTable {
  header: string[]
  align: MdTableAlign[]
  rows: string[][]
}

/** 分隔行单元格：`---` / `:--` / `--:` / `:-:` */
const DELIMITER_CELL_RE = /^:?-+:?$/

/** 按未转义的 `|` 切分一行单元格，并去掉外侧竖线产生的首尾空壳 */
export function splitTableRow(line: string): string[] {
  const cells: string[] = []
  let buf = ''
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (ch === '\\' && line[i + 1] === '|') {
      buf += '|'
      i++
      continue
    }
    if (ch === '|') {
      cells.push(buf)
      buf = ''
      continue
    }
    buf += ch
  }
  cells.push(buf)
  // GFM 允许省略外侧竖线：有竖线时会多出空的首尾单元
  if (cells.length > 1 && cells[0].trim() === '') cells.shift()
  if (cells.length > 1 && cells[cells.length - 1].trim() === '') cells.pop()
  return cells.map(cell => cell.trim())
}

/** 解析表格块；不是合法表格（无分隔行 / 分隔行格式不对）返回 null */
export function parseMdTable(text: string): MdTable | null {
  const lines = text.split('\n').filter(line => line.trim() !== '')
  if (lines.length < 2) return null

  const header = splitTableRow(lines[0])
  const delimiter = splitTableRow(lines[1])
  if (header.length === 0 || delimiter.length === 0) return null
  if (!delimiter.every(cell => DELIMITER_CELL_RE.test(cell))) return null

  const align: MdTableAlign[] = delimiter.map(cell => {
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    if (left && right) return 'center'
    if (right) return 'right'
    if (left) return 'left'
    return null
  })

  // 列宽以表头为准：多出的单元格截断、缺少的补空，避免渲染时错列
  const width = header.length
  const rows = lines.slice(2).map(line => {
    const cells = splitTableRow(line)
    return Array.from({ length: width }, (_, i) => cells[i] ?? '')
  })

  return {
    header,
    align: Array.from({ length: width }, (_, i) => align[i] ?? null),
    rows,
  }
}

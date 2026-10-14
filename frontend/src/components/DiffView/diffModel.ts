/**
 * 差异对比的纯计算模型（无 React / 无 DOM 依赖，便于单测覆盖边界）。
 *
 * 职责：
 * - `parseUnifiedDiff`：把后端 `difflib.unified_diff` 文本解析为带双端行号的差异行；
 * - `pairInline`：把相邻的「删除块 + 新增块」按序配对，为修改行计算行内高亮片段；
 * - `buildSplitRows`：把差异行重组为并排（左旧右新）行；
 * - `diffStats`：统计新增 / 删除行数。
 */

/** 差异行类型：增 / 删 / 上下文 / 区间头 / 文件头等元信息 */
export type DiffLineKind = 'add' | 'del' | 'ctx' | 'hunk' | 'meta'

/** 行内片段：`changed` 标记该片段相对另一侧发生变化 */
export interface InlineSegment {
  text: string
  changed: boolean
}

/** 解析后的差异行 */
export interface DiffLine {
  kind: DiffLineKind
  /** 去掉首列标记后的正文（hunk / meta 保留原文） */
  text: string
  /** 旧版本行号；hunk / meta / 新增行为 null */
  oldNo: number | null
  /** 新版本行号；hunk / meta / 删除行为 null */
  newNo: number | null
  /** 行内高亮片段（仅配对成功的修改行有值） */
  inline?: InlineSegment[]
}

/** 并排视图的一行：左右分别为旧 / 新侧，单侧缺失时为 null（占位对齐） */
export interface SplitRow {
  left: DiffLine | null
  right: DiffLine | null
  kind: 'ctx' | 'change' | 'hunk' | 'meta'
}

/** unified diff 区间头：`@@ -1,3 +1,4 @@` */
const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** 行内高亮 token 上限：超限退化为整行标记，避免长行 LCS 卡顿 */
const INLINE_TOKEN_LIMIT = 300
/** 行内高亮 LCS 规模上限（两侧 token 数乘积） */
const INLINE_MATRIX_LIMIT = 40_000

/**
 * 解析 unified diff 文本为差异行序列。
 *
 * 兼容：空文本、缺尾换行、`\ No newline at end of file`、区间头前的内容（`---` / `+++`）。
 */
export function parseUnifiedDiff(diff: string): DiffLine[] {
  if (!diff) return []

  const raw = diff.split('\n')
  // 以换行结尾时 split 会多出哨兵空串，仅在确为结尾时丢弃
  if (raw.length > 0 && raw[raw.length - 1] === '') raw.pop()

  const lines: DiffLine[] = []
  let oldNo = 0
  let newNo = 0
  let inHunk = false

  for (const line of raw) {
    if (line.startsWith('@@')) {
      const m = HUNK_RE.exec(line)
      if (m) {
        oldNo = Number(m[1])
        newNo = Number(m[2])
      }
      inHunk = true
      lines.push({ kind: 'hunk', text: line, oldNo: null, newNo: null })
      continue
    }
    // 区间头之前的 --- / +++ 是文件头；区间内以 -/+ 开头的正文按增删处理
    if (!inHunk && (line.startsWith('---') || line.startsWith('+++'))) {
      lines.push({ kind: 'meta', text: line, oldNo: null, newNo: null })
      continue
    }
    if (line.startsWith('\\')) {
      lines.push({ kind: 'meta', text: line, oldNo: null, newNo: null })
      continue
    }
    if (line.startsWith('+')) {
      lines.push({ kind: 'add', text: line.slice(1), oldNo: null, newNo: newNo++ })
      continue
    }
    if (line.startsWith('-')) {
      lines.push({ kind: 'del', text: line.slice(1), oldNo: oldNo++, newNo: null })
      continue
    }
    // 上下文行（difflib 正常输出带前导空格；无标记行按上下文兜底）
    lines.push({ kind: 'ctx', text: line.startsWith(' ') ? line.slice(1) : line, oldNo: oldNo++, newNo: newNo++ })
  }

  return lines
}

/** 文本 token 化：CJK 逐字、拉丁词/数字成段、空白成段、其余标点逐字符 */
function tokenize(text: string): string[] {
  return text.match(/[\u4e00-\u9fff]|[A-Za-z0-9_]+|\s+|[^\s]/g) ?? []
}

/** 求两组 token 的最长公共子序列标记：true 表示该 token 在两侧均未变化 */
function lcsFlags(a: string[], b: string[]): { aMatched: boolean[]; bMatched: boolean[] } {
  const n = a.length
  const m = b.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i]![j] = a[i] === b[j] ? dp[i + 1]![j + 1]! + 1 : Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!)
    }
  }
  const aMatched = new Array<boolean>(n).fill(false)
  const bMatched = new Array<boolean>(m).fill(false)
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      aMatched[i] = true
      bMatched[j] = true
      i++
      j++
    } else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) {
      i++
    } else {
      j++
    }
  }
  return { aMatched, bMatched }
}

/** 合并相邻同状态 token 为片段 */
function toSegments(tokens: string[], matched: boolean[]): InlineSegment[] {
  const segments: InlineSegment[] = []
  tokens.forEach((token, i) => {
    const changed = !matched[i]
    const last = segments[segments.length - 1]
    if (last && last.changed === changed) last.text += token
    else segments.push({ text: token, changed })
  })
  return segments
}

/**
 * 行内差异高亮：对配对的新旧两行做 token 级 LCS，标出真正变化的部分。
 *
 * 两侧全等 → 无高亮；一侧为空或规模超限 → 整行标记为变化（退化为行级高亮）。
 */
export function inlineSegments(
  oldText: string,
  newText: string,
): { left: InlineSegment[]; right: InlineSegment[] } {
  if (oldText === newText) {
    return { left: [{ text: oldText, changed: false }], right: [{ text: newText, changed: false }] }
  }
  const a = tokenize(oldText)
  const b = tokenize(newText)
  const tooLarge =
    a.length > INLINE_TOKEN_LIMIT || b.length > INLINE_TOKEN_LIMIT || a.length * b.length > INLINE_MATRIX_LIMIT
  if (a.length === 0 || b.length === 0 || tooLarge) {
    return { left: [{ text: oldText, changed: true }], right: [{ text: newText, changed: true }] }
  }
  const { aMatched, bMatched } = lcsFlags(a, b)
  return { left: toSegments(a, aMatched), right: toSegments(b, bMatched) }
}

/**
 * 为相邻的「删除块 + 新增块」按序配对并写入行内高亮片段。
 *
 * 返回浅拷贝后的新数组，不修改入参。
 */
export function pairInline(lines: DiffLine[]): DiffLine[] {
  const result = lines.map((line) => ({ ...line }))
  let i = 0
  while (i < result.length) {
    if (result[i]!.kind !== 'del') {
      i++
      continue
    }
    let delEnd = i
    while (delEnd < result.length && result[delEnd]!.kind === 'del') delEnd++
    let addEnd = delEnd
    while (addEnd < result.length && result[addEnd]!.kind === 'add') addEnd++

    const delCount = delEnd - i
    const addCount = addEnd - delEnd
    if (addCount > 0) {
      for (let k = 0; k < Math.min(delCount, addCount); k++) {
        const delLine = result[i + k]!
        const addLine = result[delEnd + k]!
        const { left, right } = inlineSegments(delLine.text, addLine.text)
        delLine.inline = left
        addLine.inline = right
      }
    }
    i = addEnd > delEnd ? addEnd : delEnd
  }
  return result
}

/** 把差异行重组为并排行：删除块与随后的新增块逐行配对，单侧不足补 null */
export function buildSplitRows(lines: DiffLine[]): SplitRow[] {
  const rows: SplitRow[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    if (line.kind === 'del') {
      let delEnd = i
      while (delEnd < lines.length && lines[delEnd]!.kind === 'del') delEnd++
      let addEnd = delEnd
      while (addEnd < lines.length && lines[addEnd]!.kind === 'add') addEnd++
      const dels = lines.slice(i, delEnd)
      const adds = lines.slice(delEnd, addEnd)
      for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
        rows.push({ left: dels[k] ?? null, right: adds[k] ?? null, kind: 'change' })
      }
      i = addEnd
      continue
    }
    if (line.kind === 'add') {
      // 无前导删除块的孤立新增行
      rows.push({ left: null, right: line, kind: 'change' })
      i++
      continue
    }
    rows.push({ left: line, right: line, kind: line.kind === 'ctx' ? 'ctx' : line.kind })
    i++
  }
  return rows
}

/** 统计新增 / 删除行数（与渲染行一致，不含文件头与区间头） */
export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0
  let removed = 0
  for (const line of lines) {
    if (line.kind === 'add') added++
    else if (line.kind === 'del') removed++
  }
  return { added, removed }
}

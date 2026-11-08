/** 结构 DSL 缩进与花括号对齐（需求卡 0127 P0）.
 *
 * 花括号 DSL 的缩进只由 `{` / `}` 深度决定：固定 2 空格，Tab 也只写空格；
 * 计算前复用 `stripCommentsAndStrings` 剥离字符串与注释，避免误计字符串里的括号；
 * `[` 向量不参与缩进计算。智能回车优先于 `defaultKeymap`。
 */

import type { IndentContext } from '@codemirror/language'
import type { EditorView } from '@codemirror/view'
import { stripCommentsAndStrings } from './designCompletion'

/** 缩进单位：固定 2 空格（C3） */
export const DSL_INDENT_UNIT = '  '

/** 光标前的花括号净深度（字符串 / 注释内的括号不计） */
function braceDepthBefore(doc: string, pos: number): number {
  const stripped = stripCommentsAndStrings(doc)
  const end = Math.min(pos, stripped.length)
  let depth = 0
  for (let i = 0; i < end; i += 1) {
    const ch = stripped[i]
    if (ch === '{') depth += 1
    else if (ch === '}') depth = Math.max(0, depth - 1)
  }
  return depth
}

/** 指定行文本的缩进列数：行首为 `}` 时回退一层（C4） */
function lineIndent(doc: string, lineFrom: number, lineText: string): number {
  const depth = braceDepthBefore(doc, lineFrom)
  const effective = lineText.trimStart().startsWith('}') ? depth - 1 : depth
  return Math.max(0, effective) * DSL_INDENT_UNIT.length
}

/** 光标所在行的目标缩进列数（单测入口） */
export function indentAt(doc: string, pos: number): number {
  const lineFrom = doc.lastIndexOf('\n', Math.max(0, pos - 1)) + 1
  const lineEnd = doc.indexOf('\n', lineFrom)
  const lineText = doc.slice(lineFrom, lineEnd === -1 ? doc.length : lineEnd)
  return lineIndent(doc, lineFrom, lineText)
}

/** CodeMirror 缩进服务：默认回车与 `}` 自动回退共用（C4） */
export function dslIndentService(context: IndentContext, pos: number): number | null {
  return indentAt(context.state.doc.toString(), pos)
}

/** 空行 / 其他行继承当前缩进；行尾 `{` 进入下一层 */
function nextLineIndent(before: string): string {
  const indent = /^[ \t]*/.exec(before)?.[0] ?? ''
  const stripped = stripCommentsAndStrings(before)
  if (/\{\s*$/.test(stripped)) return indent + DSL_INDENT_UNIT
  return indent
}

/** 回车：花括号结构感知（C4）.
 *
 * - 自动配对 `{}` 之间：展开三行，右花括号与 `{` 所在行对齐；
 * - 行尾 `{`：下一行进一层；
 * - 空行 / 其他行：继承当前缩进，不自动回退；
 * - 非空选区：按普通回车替换选区，不猜缩进。
 */
export function insertDslNewline(view: EditorView): boolean {
  const { state } = view
  const range = state.selection.main
  if (!range.empty) {
    view.dispatch(state.replaceSelection('\n'))
    return true
  }
  const line = state.doc.lineAt(range.head)
  const before = line.text.slice(0, range.head - line.from)
  const after = line.text.slice(range.head - line.from)
  const currentIndent = /^[ \t]*/.exec(before)?.[0] ?? ''
  const strippedBefore = stripCommentsAndStrings(before)

  // 光标位于自动配对的 `{}` 之间：吞掉两括号间的空白，展开为三行
  const autoClose = /^[ \t]*\}/.exec(after)
  if (autoClose && /\{\s*$/.test(strippedBefore)) {
    const innerIndent = currentIndent + DSL_INDENT_UNIT
    const insert = `\n${innerIndent}\n${currentIndent}`
    view.dispatch({
      changes: { from: range.head, to: range.head + autoClose[0].length - 1, insert },
      selection: { anchor: range.head + 1 + innerIndent.length },
    })
    return true
  }

  view.dispatch(state.replaceSelection(`\n${nextLineIndent(before)}`))
  return true
}

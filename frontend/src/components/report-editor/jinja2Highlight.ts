/**
 * CodeMirror 6 Jinja2 语法高亮扩展.
 *
 * 识别三类 Jinja2 标记：
 * - {{ ... }}  → 变量/表达式
 * - {% ... %}  → 控制语句
 * - {# ... #}  → 注释
 *
 * 基于 Decoration.mark 实现，不依赖外部语言包。
 */

import { EditorView, Decoration, DecorationSet } from '@codemirror/view'
import { StateField, EditorState } from '@codemirror/state'

// ── Token 正则 ──────────────────────────────────────────────────
const JINJA_PATTERN = /(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}|\{#[\s\S]*?#\})/g

function tokenClass(match: string): string {
  if (match.startsWith('{{')) return 'cm-jinja-variable'
  if (match.startsWith('{%')) return 'cm-jinja-statement'
  return 'cm-jinja-comment'
}

// ── Decoration ──────────────────────────────────────────────────
function buildDecos(state: EditorState): DecorationSet {
  const text = state.doc.toString()
  const ranges = [] as Array<{ from: number; to: number; value: Decoration }>
  let m: RegExpExecArray | null
  JINJA_PATTERN.lastIndex = 0
  while ((m = JINJA_PATTERN.exec(text)) !== null) {
    const cls = tokenClass(m[0])
    ranges.push({
      from: m.index,
      to: m.index + m[0].length,
      value: Decoration.mark({ class: cls }),
    })
  }
  return Decoration.set(ranges, true)
}

export const jinja2StateField = StateField.define<DecorationSet>({
  create(state) { return buildDecos(state) },
  update(decos, tr) {
    return tr.docChanged ? buildDecos(tr.state) : decos.map(tr.changes)
  },
  provide(field) {
    return EditorView.decorations.from(field)
  },
})

/** 一键安装的扩展，放入 EditorView.extensions */
export function jinja2Extensions() {
  return [jinja2StateField]
}

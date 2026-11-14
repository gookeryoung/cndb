/** 实时预览编辑器的「回车」命令：延续 Markdown 列表 / 引用标记，但**不再额外插入空行**.
 *
 * `@codemirror/lang-markdown` 的 `insertNewlineContinueMarkup` 在两种情况下会多插一行：
 * - 列表本身是 loose list（项之间已有空行）时，为「保持 loose」在每个新项前补一行；
 * - 紧凑列表里对第二个空项回车时，把空项上移成 loose list。
 * 对写文档的人来说，回车应当只新增一行（+ 延续标记），空行由用户自己决定，
 * 所以这里：① 关掉空项上移行为；② 把上游插入文本里的「空行 + 换行」收成单个换行。
 *
 * 非 Markdown 上下文（普通段落 / 代码块等）仍返回 false，交回 CodeMirror 默认回车。
 */

import type { StateCommand, Text, Transaction } from '@codemirror/state'
import { insertNewlineContinueMarkupCommand } from '@codemirror/lang-markdown'

/** 去掉插入文本里的空行（只含缩进 / 引用符的行），其余缩进与引用符保持原样 */
export function collapseBlankLine(text: string): string {
  return text.replace(/\n[ \t>]*\n/g, '\n')
}

export function continueMarkupSingleLine(): StateCommand {
  const upstream = insertNewlineContinueMarkupCommand({ nonTightLists: false })
  return ({ state, dispatch }) => {
    let tr: Transaction | null = null
    const handled = upstream({ state, dispatch: t => { tr = t } })
    // 上游同步 dispatch，但 TS 不追踪回调内赋值：显式取一次再做空值收窄
    const result = tr as Transaction | null
    if (!handled || !result) return false

    const head = result.state.selection.main.head
    let removed = 0
    const specs: { from: number; to: number; insert: string }[] = []
    result.changes.iterChanges((fromA: number, toA: number, _fromB: number, _toB: number, inserted: Text) => {
      const text = inserted.toString()
      const collapsed = collapseBlankLine(text)
      if (collapsed !== text && toA <= head) removed += text.length - collapsed.length
      specs.push({ from: fromA, to: toA, insert: collapsed })
    })

    // 上游没有补空行：直接采用它的结果（保留选区 / 滚动 / 记号语义）
    if (removed === 0) {
      dispatch(result)
      return true
    }
    const changes = state.changes(specs)
    dispatch(
      state.update({
        changes,
        selection: { anchor: Math.max(0, head - removed) },
        scrollIntoView: true,
        userEvent: 'input',
      }),
    )
    return true
  }
}

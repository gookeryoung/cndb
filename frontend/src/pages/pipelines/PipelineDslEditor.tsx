/** 流水线 DSL 编辑器 —— CodeMirror 6 封装（需求卡 0111 P0-P2）.
 *
 * 口径对齐设计模块 `design/DslEditor.tsx`：受控 value 同步 / updateListener /
 * 个人设置里的编辑器配色与字体 / StreamLanguage 高亮；本组件额外挂 `lineNumbers`、
 * 空白可视化、2 空格智能缩进与自动完成（关键字 / 规则引用 / 本地引用 / 片段）。
 */

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { Compartment, EditorState } from '@codemirror/state'
import {
  EditorView,
  highlightWhitespace,
  keymap,
  lineNumbers,
  placeholder as cmPlaceholder,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { indentUnit } from '@codemirror/language'
import { autocompletion } from '@codemirror/autocomplete'
import { useEditorAppearance } from '@/theme/ThemeProvider'
import { editorAppearanceExtensions } from '@/theme/editorAppearance'
import { DSL_INDENT_UNIT, insertDslNewline, pipelineDslLanguage } from './pipelineDsl'
import { pipelineCompletionSource, type PipelineCheckLike } from './pipelineCompletion'

/** 外观仓：跟随个人设置里的编辑器主题 / 字体实时重配 */
const appearanceCompartment = new Compartment()

/** 编辑器对宿主暴露的操作（检查目录「插入」按钮用，C7） */
export interface PipelineDslEditorHandle {
  /** 在光标处插入文本；当前行已有内容时先换行，避免与上一行粘连 */
  insertSnippet: (text: string) => void
  focus: () => void
}

interface PipelineDslEditorProps {
  value: string
  onChange: (value: string) => void
  /** 检查动作目录（补全数据源，由宿主页注入，C5） */
  checks?: readonly PipelineCheckLike[]
  /** 当前检查域（完整 workflow 骨架模板，C7） */
  domain?: 'table' | 'document'
  placeholder?: string
}

const PipelineDslEditor = forwardRef<PipelineDslEditorHandle, PipelineDslEditorProps>(
  function PipelineDslEditor({ value, onChange, checks, domain, placeholder }, ref) {
    const hostRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const onChangeRef = useRef(onChange)
    onChangeRef.current = onChange
    const checksRef = useRef(checks)
    checksRef.current = checks
    const domainRef = useRef(domain)
    domainRef.current = domain
    const { isDark, editor } = useEditorAppearance()

    // 视图只建一次；外部 value 变化（保存失败回显 / 草稿恢复）以 transaction 同步
    useEffect(() => {
      const host = hostRef.current
      if (!host) return
      const view = new EditorView({
        parent: host,
        state: EditorState.create({
          doc: value,
          extensions: [
            lineNumbers(),
            // 空白可视化：空格显示为点、Tab 显示为箭头（C4）
            highlightWhitespace(),
            history(),
            keymap.of([
              { key: 'Enter', run: insertDslNewline },
              ...defaultKeymap,
              ...historyKeymap,
              indentWithTab,
            ]),
            // 缩进固定 2 空格，Tab / 自动缩进都只写空格（C3-C5）
            indentUnit.of(DSL_INDENT_UNIT),
            EditorState.tabSize.of(DSL_INDENT_UNIT.length),
            pipelineDslLanguage,
            appearanceCompartment.of(
              editorAppearanceExtensions(editor.theme, isDark, editor.font),
            ),
            EditorView.lineWrapping,
            EditorView.contentAttributes.of({ 'aria-label': '流水线 YAML' }),
            autocompletion({
              activateOnTyping: true,
              override: [context => pipelineCompletionSource(context, {
                checks: checksRef.current,
                domain: domainRef.current,
              })],
            }),
            placeholder ? cmPlaceholder(placeholder) : [],
            EditorView.updateListener.of(update => {
              if (update.docChanged) onChangeRef.current(update.state.doc.toString())
            }),
          ],
        }),
      })
      viewRef.current = view
      return () => {
        view.destroy()
        viewRef.current = null
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps -- 视图仅按初始 value 建一次
    }, [])

    // 受控 value 同步
    useEffect(() => {
      const view = viewRef.current
      if (view && view.state.doc.toString() !== value) {
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
      }
    }, [value])

    // 编辑器配色 / 字体变更（个人设置 → 主题 → 编辑器）即时生效，不重建视图
    useEffect(() => {
      viewRef.current?.dispatch({
        effects: appearanceCompartment.reconfigure(
          editorAppearanceExtensions(editor.theme, isDark, editor.font),
        ),
      })
    }, [editor, isDark])

    useImperativeHandle(ref, () => ({
      insertSnippet: (text: string) => {
        const view = viewRef.current
        if (!view) return
        const { state } = view
        const head = state.selection.main.head
        const line = state.doc.lineAt(head)
        const before = state.doc.sliceString(line.from, head)
        const separator = before.trim() ? '\n' : ''
        view.dispatch(state.replaceSelection(`${separator}${text}`))
        view.focus()
      },
      focus: () => viewRef.current?.focus(),
    }), [])

    return <div ref={hostRef} className="cn-dsl-editor cn-pipeline-editor" data-testid="pipeline-dsl-editor" />
  },
)

export default PipelineDslEditor

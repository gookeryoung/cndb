import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { bracketMatching, indentOnInput, foldGutter, foldKeymap } from '@codemirror/language'
import { oneDark } from '@codemirror/theme-one-dark'
import { jinja2Extensions } from './jinja2Highlight'

export interface TemplateEditorHandle {
  /** 在当前光标位置插入文本（处理选区替换） */
  insertText: (text: string) => void
  /** 获取当前全文 */
  getValue: () => string
  /** 程序式设置全文（如加载存量模板） */
  setValue: (text: string) => void
  /** 设置只读/可编辑 */
  setReadOnly: (readonly: boolean) => void
  /** 聚焦编辑器 */
  focus: () => void
}

export interface TemplateEditorProps {
  value: string
  onChange: (value: string) => void
  readOnly?: boolean
  /** 是否作为拖拽目标（dropzone 激活时显示高亮边框） */
  isDragActive?: boolean
}

const TemplateEditor = forwardRef<TemplateEditorHandle, TemplateEditorProps>(function TemplateEditor(
  { value, onChange, readOnly = false, isDragActive = false },
  ref,
) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const skipNextChangeRef = useRef(false)

  // 初始化 CodeMirror（仅一次）
  useEffect(() => {
    if (!hostRef.current || viewRef.current) return

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged && !skipNextChangeRef.current) {
        onChange(update.state.doc.toString())
      }
      skipNextChangeRef.current = false
    })

    const startState = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        foldGutter(),
        bracketMatching(),
        indentOnInput(),
        history(),
        keymap.of([...defaultKeymap, ...historyKeymap, ...foldKeymap, indentWithTab]),
        jinja2Extensions(),
        oneDark,
        updateListener,
        EditorView.theme({
          '&': {
            height: '100%',
            fontSize: '14px',
          },
          '.cm-scroller': {
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            lineHeight: '1.6',
          },
          '.cm-jinja-variable': {
            color: '#7ec699',
            fontWeight: 'bold',
          },
          '.cm-jinja-statement': {
            color: '#f0a988',
            fontWeight: 'bold',
          },
          '.cm-jinja-comment': {
            color: '#888888',
            fontStyle: 'italic',
          },
          '.cm-gutters': {
            backgroundColor: '#21252b',
            color: '#5c6370',
          },
        }),
      ],
    })

    viewRef.current = new EditorView({ state: startState, parent: hostRef.current })

    return () => {
      viewRef.current?.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 受控 value 同步到 CodeMirror（外部 setValue 触发）
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const current = view.state.doc.toString()
    if (current !== value) {
      skipNextChangeRef.current = true
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      })
    }
  }, [value])

  // readOnly 切换 — 动态切换较复杂，仅通过 DOM 属性标记
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    if (readOnly) {
      view.contentDOM.setAttribute('aria-readonly', 'true')
    } else {
      view.contentDOM.removeAttribute('aria-readonly')
    }
  }, [readOnly])

  // 暴露 imperative handle
  useImperativeHandle(ref, () => ({
    insertText: (text: string) => {
      const view = viewRef.current
      if (!view) return
      const { from, to } = view.state.selection.main
      view.dispatch({
        changes: { from, to, insert: text },
        selection: { anchor: from + text.length },
      })
      view.focus()
    },
    getValue: () => viewRef.current?.state.doc.toString() ?? '',
    setValue: (text: string) => {
      const view = viewRef.current
      if (!view) return
      const current = view.state.doc.toString()
      skipNextChangeRef.current = true
      view.dispatch({
        changes: { from: 0, to: current.length, insert: text },
      })
    },
    setReadOnly: (_readonly: boolean) => {
      // 简化：暂不支持运行时切换 editable
      // CodeMirror 6 运行时切换需要 reconfigure state field，较复杂
    },
    focus: () => {
      viewRef.current?.focus()
    },
  }))

  return (
    <div
      ref={hostRef}
      className={`report-codemirror-host ${isDragActive ? 'dropzone-active' : ''}`}
      data-dropzone={isDragActive ? 'active' : 'inactive'}
    />
  )
})

export default TemplateEditor

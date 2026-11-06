/** 结构 DSL 编辑器 —— CodeMirror 6 封装（ADR 0079 D11）.
 *
 * StreamLanguage 高亮见 designLang；诊断回显：编译端点返回的结构化
 * diagnostics（行 / 列）映射为错误行装饰（`cn-dsl-diag-error` 底色），
 * doc 变更后旧装饰立即失效（等下一轮编译结果），避免错位。
 */

import { useEffect, useRef } from 'react'
import { Compartment, EditorState, StateEffect, StateField } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  keymap,
  lineNumbers,
  placeholder as cmPlaceholder,
  type DecorationSet,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { autocompletion } from '@codemirror/autocomplete'
import type { DesignDiagnostic } from '@/api'
import { useEditorAppearance } from '@/theme/ThemeProvider'
import { editorAppearanceExtensions } from '@/theme/editorAppearance'
import { cnDslLanguage } from './designLang'
import { dslCompletionSource, type DslPartOption } from './designCompletion'

/** 诊断更新效果（编辑器外部把编译结果推进来） */
export const setDiagnostics = StateEffect.define<DesignDiagnostic[]>()

const diagnosticsField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setDiagnostics)) {
        const doc = tr.state.doc
        const ranges = effect.value.map(item => {
          const line = Math.min(Math.max(item.line, 1), doc.lines)
          const pos = doc.line(line).from
          return Decoration.line({ class: 'cn-dsl-diag-error' }).range(pos)
        })
        return Decoration.set(ranges)
      }
    }
    // 文档变更后旧定位失效：清空装饰，等下一轮编译
    return tr.docChanged ? Decoration.none : value
  },
  provide: field => EditorView.decorations.from(field),
})

/** 只读切换仓（viewer 只读看源码） */
const editableCompartment = new Compartment()
/** 自动完成仓：只读 viewer 不挂补全扩展（C5） */
const completionCompartment = new Compartment()
/** 外观仓：跟随个人设置里的编辑器主题 / 字体实时重配 */
const appearanceCompartment = new Compartment()

interface DslEditorProps {
  value: string
  onChange: (value: string) => void
  diagnostics: DesignDiagnostic[]
  placeholder?: string
  /** 只读态（viewer）：内容可看不可改 */
  readOnly?: boolean
  /** 定位到指定源行（1 基，来自设计结构树节点；越界钳制到末行，ADR 0083 D7） */
  revealLine?: number
  /** 跨文件零件名获取函数（P2，由宿主页注入；编辑器组件不直接依赖 api 层） */
  fetchParts?: () => Promise<readonly DslPartOption[]>
}

/** 补全扩展：标识符输入自动触发，Ctrl+Space 手动唤起（C5） */
function makeCompletionExtension(fetch?: () => Promise<readonly DslPartOption[]>) {
  return autocompletion({
    activateOnTyping: true,
    override: [context => dslCompletionSource(context, { fetchParts: fetch })],
  })
}

export default function DslEditor({
  value, onChange, diagnostics, placeholder, readOnly, revealLine, fetchParts,
}: DslEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const fetchPartsRef = useRef(fetchParts)
  fetchPartsRef.current = fetchParts
  const { isDark, editor } = useEditorAppearance()

  // 视图只建一次；外部 value 变化（保存后回写等）以 transaction 同步
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          cnDslLanguage,
          appearanceCompartment.of(
            editorAppearanceExtensions(editor.theme, isDark, editor.font),
          ),
          diagnosticsField,
          EditorView.lineWrapping,
          placeholder ? cmPlaceholder(placeholder) : [],
          editableCompartment.of(EditorView.editable.of(!readOnly)),
          completionCompartment.of(readOnly ? [] : makeCompletionExtension(fetchPartsRef.current)),
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

  // 受控 value 同步（草稿恢复 / 保存失败回显不丢）
  useEffect(() => {
    const view = viewRef.current
    if (view && view.state.doc.toString() !== value) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
    }
  }, [value])

  // 只读切换（viewer 也能看设计源；补全扩展同步摘除，C5）
  useEffect(() => {
    viewRef.current?.dispatch({
      effects: [
        editableCompartment.reconfigure(EditorView.editable.of(!readOnly)),
        completionCompartment.reconfigure(readOnly ? [] : makeCompletionExtension(fetchPartsRef.current)),
      ],
    })
  }, [readOnly])

  // 编辑器配色 / 字体变更（个人设置 → 主题 → 编辑器）即时生效，不重建视图
  useEffect(() => {
    viewRef.current?.dispatch({
      effects: appearanceCompartment.reconfigure(
        editorAppearanceExtensions(editor.theme, isDark, editor.font),
      ),
    })
  }, [editor, isDark])

  // 诊断装饰同步（错误行底色）
  useEffect(() => {
    viewRef.current?.dispatch({ effects: setDiagnostics.of(diagnostics) })
  }, [diagnostics])

  // 源行定位（结构树节点点击跳转，ADR 0083 D7）：选中该行并滚动到视口中部
  useEffect(() => {
    const view = viewRef.current
    if (!view || !revealLine || revealLine < 1) return
    const line = Math.min(revealLine, view.state.doc.lines)
    const range = view.state.doc.line(line)
    view.dispatch({
      selection: { anchor: range.from, head: range.to },
      effects: EditorView.scrollIntoView(range.from, { y: 'center' }),
    })
    view.focus()
  }, [revealLine])

  return <div ref={hostRef} className="cn-dsl-editor" />
}

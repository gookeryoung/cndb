/** Obsidian 风格 Markdown 编辑器：实时预览（隐藏语法标记 + 渲染元素）与源码双模式.
 *
 * 设计要点：
 * - **实时预览**用 CodeMirror 6 + `@codemirror/lang-markdown`，基于语法树给可见范围
 *   加装饰：语法标记（`#` / `**` / `` ` `` / 链接符号）在光标离开该元素时隐藏，
 *   标题、加粗、斜体、行内代码、引用、代码块、分隔线、图片按渲染态显示；
 *   光标进入对应元素后自动还原为源码，便于精确编辑（与 Obsidian 一致）。
 * - **源码模式**保留原生 textarea：行为与旧编辑器完全一致（查找替换、快捷键、
 *   段落锁都基于字符偏移），也便于无障碍与输入法。
 * - 两种模式共用一套命令式句柄（选区 / 定位 / 聚焦），上层无需感知实现差异。
 */

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import type { CSSProperties } from 'react'
import { EditorState, Facet, type Range } from '@codemirror/state'
import {
  Decoration,
  type DecorationSet,
  EditorView,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
  drawSelection,
  keymap,
  placeholder as cmPlaceholder,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { syntaxTree } from '@codemirror/language'
import { markdown, markdownLanguage } from '@codemirror/lang-markdown'
import { Input } from 'antd'
import type { TextAreaRef } from 'antd/es/input/TextArea'

import { loadFileObjectUrl } from '@/hooks/useFileObjectUrl'
import { parseImageRef } from './imageRef'

export type MarkdownEditorMode = 'live' | 'source'

/** 编辑器快捷键动作（由页面决定具体行为） */
export type MarkdownEditorShortcut = 'find' | 'bold' | 'italic' | 'link' | 'escape'

export interface MarkdownEditorHandle {
  /** 当前选区（字符偏移） */
  getSelection: () => { start: number; end: number }
  /** 设置选区并聚焦（end 缺省 = start） */
  setSelection: (start: number, end?: number) => void
  /** 聚焦编辑器 */
  focus: () => void
  /** 滚动到指定偏移（段落跳转 / 查找定位） */
  revealOffset: (offset: number) => void
}

interface MarkdownLiveEditorProps {
  value: string
  mode: MarkdownEditorMode
  workspaceId?: number | string
  placeholder?: string
  onChange: (value: string) => void
  /** 光标/选区变化回调（段落锁按光标所在段获取） */
  onCaret?: (offset: number) => void
  /** 粘贴图片：由调用方上传并插入引用 */
  onPasteImages?: (files: File[]) => void
  /** Ctrl/Cmd+F/H/B/I/K */
  onShortcut?: (action: MarkdownEditorShortcut) => void
  style?: CSSProperties
}

// ── 图片组件：站内 file:<key> 走鉴权 blob，外部 URL 直出 ──

class MarkdownImageWidget extends WidgetType {
  constructor(
    private readonly src: string,
    private readonly alt: string,
    private readonly workspaceId: number | string | undefined,
  ) {
    super()
  }

  eq(other: MarkdownImageWidget): boolean {
    return other.src === this.src && other.alt === this.alt && other.workspaceId === this.workspaceId
  }

  toDOM(): HTMLElement {
    const wrap = document.createElement('span')
    wrap.className = 'cm-md-image'
    const fileKey = parseImageRef(this.src)
    if (!fileKey) {
      const img = document.createElement('img')
      img.src = this.src
      img.alt = this.alt
      img.loading = 'lazy'
      wrap.appendChild(img)
      return wrap
    }
    if (this.workspaceId === undefined || this.workspaceId === null) {
      wrap.textContent = this.alt || '图片'
      return wrap
    }
    const img = document.createElement('img')
    img.alt = this.alt
    img.loading = 'lazy'
    img.style.display = 'none'
    wrap.appendChild(img)
    loadFileObjectUrl(this.workspaceId, fileKey).then(
      url => {
        img.src = url
        img.style.display = ''
      },
      () => {
        wrap.textContent = `图片加载失败（${fileKey}）`
      },
    )
    return wrap
  }

  ignoreEvent(): boolean {
    return false
  }
}

// ── 实时预览装饰 ──────────────────────────────────────

const HEADING_RE = /^(?:ATX|Setext)Heading(\d)$/
const EMPHASIS_CLASS: Record<string, string> = {
  Emphasis: 'cm-md-em',
  StrongEmphasis: 'cm-md-strong',
  Strikethrough: 'cm-md-strike',
}
const MARK_NAMES: Record<string, string[]> = {
  Emphasis: ['EmphasisMark'],
  StrongEmphasis: ['EmphasisMark'],
  Strikethrough: ['StrikethroughMark'],
}
const IMAGE_RE = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)$/

function hide(from: number, to: number): Range<Decoration> | null {
  return to > from ? Decoration.replace({}).range(from, to) : null
}

/** 构建可见范围的装饰：语法标记隐藏 + 元素样式 + 图片/分隔线渲染 */
function buildDecorations(view: EditorView): DecorationSet {
  const ranges: Range<Decoration>[] = []
  const doc = view.state.doc
  const cursor = view.state.selection.main.head
  const active = (from: number, to: number) => cursor >= from && cursor <= to
  const push = (deco: Range<Decoration> | null) => {
    if (deco) ranges.push(deco)
  }

  for (const { from, to } of view.visibleRanges) {
    syntaxTree(view.state).iterate({
      from,
      to,
      enter: node => {
        const name = node.name
        const nodeActive = active(node.from, node.to)
        const heading = HEADING_RE.exec(name)
        if (heading) {
          const level = heading[1]
          ranges.push(Decoration.line({ class: `cm-md-heading cm-md-h${level}` }).range(doc.lineAt(node.from).from))
          const marks = node.node.getChildren('HeaderMark')
          if (!nodeActive) {
            for (const mark of marks) {
              // setext 下划线连同换行一起隐藏，避免留下一行空白
              const until = name.startsWith('Setext') ? Math.min(mark.to + 1, doc.length) : mark.to
              push(hide(mark.from, until))
            }
          }
          return
        }

        const emphasisClass = EMPHASIS_CLASS[name]
        if (emphasisClass) {
          if (!nodeActive) {
            ranges.push(Decoration.mark({ class: emphasisClass }).range(node.from, node.to))
            for (const markName of MARK_NAMES[name] ?? []) {
              for (const mark of node.node.getChildren(markName)) push(hide(mark.from, mark.to))
            }
          }
          return
        }

        if (name === 'InlineCode') {
          ranges.push(Decoration.mark({ class: 'cm-md-code' }).range(node.from, node.to))
          if (!nodeActive) {
            for (const mark of node.node.getChildren('CodeMark')) push(hide(mark.from, mark.to))
          }
          return
        }

        if (name === 'Link') {
          if (nodeActive) return
          ranges.push(Decoration.mark({ class: 'cm-md-link' }).range(node.from, node.to))
          for (const markName of ['LinkMark', 'URL', 'LinkTitle']) {
            for (const mark of node.node.getChildren(markName)) push(hide(mark.from, mark.to))
          }
          return
        }

        if (name === 'Image') {
          if (nodeActive) return
          const raw = doc.sliceString(node.from, node.to)
          const parsed = IMAGE_RE.exec(raw)
          if (parsed) {
            ranges.push(
              Decoration.replace({
                widget: new MarkdownImageWidget(parsed[2], parsed[1], view.state.facet(imageContext)),
              }).range(node.from, node.to),
            )
          }
          return
        }

        if (name === 'HorizontalRule') {
          const line = doc.lineAt(node.from)
          ranges.push(Decoration.line({ class: 'cm-md-hr' }).range(line.from))
          if (!nodeActive) push(hide(node.from, node.to))
          return
        }

        if (name === 'Blockquote') {
          let pos = node.from
          while (pos <= node.to) {
            const line = doc.lineAt(pos)
            ranges.push(Decoration.line({ class: 'cm-md-quote' }).range(line.from))
            if (line.to >= node.to) break
            pos = line.to + 1
          }
          if (!nodeActive) {
            for (const mark of node.node.getChildren('QuoteMark')) push(hide(mark.from, mark.to))
          }
          return
        }

        if (name === 'FencedCode' || name === 'CodeBlock') {
          let pos = node.from
          while (pos <= node.to) {
            const line = doc.lineAt(pos)
            ranges.push(Decoration.line({ class: 'cm-md-codeblock' }).range(line.from))
            if (line.to >= node.to) break
            pos = line.to + 1
          }
          return
        }

        if (name === 'ListMark') {
          ranges.push(Decoration.mark({ class: 'cm-md-listmark' }).range(node.from, node.to))
        }
      },
    })
  }

  return Decoration.set(ranges, true)
}

/** 图片组件需要工作区上下文：用 facet 传递给 widget（widget 无法使用 React hook） */
const imageContext = Facet.define<number | string | undefined, number | string | undefined>({
  combine: values => values[values.length - 1],
})

const livePreviewPlugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet

    constructor(view: EditorView) {
      this.decorations = buildDecorations(view)
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.selectionSet || update.viewportChanged) {
        this.decorations = buildDecorations(update.view)
      }
    }
  },
  { decorations: plugin => plugin.decorations },
)

// ── 主题（跟随应用 CSS 变量，明暗主题自动适配）────────

const editorTheme = EditorView.theme({
  '&': {
    height: '100%',
    backgroundColor: 'var(--cn-bg-container, #fff)',
    color: 'var(--cn-text-primary, #1f2937)',
    fontSize: '14px',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': {
    fontFamily: 'var(--cn-font-sans, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif)',
    lineHeight: '1.75',
    overflow: 'auto',
  },
  '.cm-content': { padding: '16px 20px', caretColor: 'var(--cn-brand-color, #1677ff)' },
  '.cm-line': { padding: '0' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--cn-text-primary, #1f2937)' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection': {
    backgroundColor: 'color-mix(in srgb, var(--cn-brand-color, #1677ff) 22%, transparent)',
  },
  '.cm-placeholder': { color: 'var(--cn-text-muted, #9ca3af)' },
  '.cm-md-heading': { fontWeight: '700', lineHeight: '1.4' },
  '.cm-md-h1': { fontSize: '1.75em' },
  '.cm-md-h2': { fontSize: '1.45em' },
  '.cm-md-h3': { fontSize: '1.25em' },
  '.cm-md-h4': { fontSize: '1.1em' },
  '.cm-md-h5': { fontSize: '1em' },
  '.cm-md-h6': { fontSize: '0.95em', color: 'var(--cn-text-secondary, #6b7280)' },
  '.cm-md-em': { fontStyle: 'italic' },
  '.cm-md-strong': { fontWeight: '700' },
  '.cm-md-strike': { textDecoration: 'line-through' },
  '.cm-md-code': {
    fontFamily: 'var(--cn-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace)',
    backgroundColor: 'var(--cn-bg-subtle, #fafafa)',
    borderRadius: '4px',
    padding: '1px 4px',
    fontSize: '0.92em',
  },
  '.cm-md-link': { color: 'var(--cn-brand-color, #1677ff)', textDecoration: 'underline' },
  '.cm-md-listmark': { color: 'var(--cn-brand-color, #1677ff)' },
  '.cm-md-quote': {
    borderLeft: '3px solid var(--cn-border, #e5e7eb)',
    paddingLeft: '12px',
    color: 'var(--cn-text-secondary, #6b7280)',
  },
  '.cm-md-hr': { borderTop: '1px solid var(--cn-border, #e5e7eb)' },
  '.cm-md-codeblock': {
    fontFamily: 'var(--cn-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace)',
    backgroundColor: 'var(--cn-bg-subtle, #fafafa)',
    fontSize: '0.92em',
  },
  '.cm-md-image': { display: 'inline-flex', alignItems: 'center', maxWidth: '100%' },
  '.cm-md-image img': { maxWidth: '100%', maxHeight: '320px', borderRadius: '6px', verticalAlign: 'middle' },
})

const EDITOR_STYLE: CSSProperties = { flex: 1, minHeight: 0, overflow: 'hidden' }

const MarkdownLiveEditor = forwardRef<MarkdownEditorHandle, MarkdownLiveEditorProps>(function MarkdownLiveEditor(
  { value, mode, workspaceId, placeholder, onChange, onCaret, onPasteImages, onShortcut, style },
  ref,
) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const taRef = useRef<TextAreaRef>(null)

  // 用 ref 持有回调，避免父组件每次渲染都重建 EditorView（丢撤销栈与光标）
  const onChangeRef = useRef(onChange)
  const onCaretRef = useRef(onCaret)
  const onPasteRef = useRef(onPasteImages)
  const onShortcutRef = useRef(onShortcut)
  useEffect(() => {
    onChangeRef.current = onChange
    onCaretRef.current = onCaret
    onPasteRef.current = onPasteImages
    onShortcutRef.current = onShortcut
  })

  useImperativeHandle(ref, () => ({
    getSelection: () => {
      const view = viewRef.current
      if (view) {
        const { from, to } = view.state.selection.main
        return { start: from, end: to }
      }
      const ta = taRef.current?.resizableTextArea?.textArea
      return { start: ta?.selectionStart ?? 0, end: ta?.selectionEnd ?? 0 }
    },
    setSelection: (start, end = start) => {
      const view = viewRef.current
      if (view) {
        view.dispatch({ selection: { anchor: start, head: end }, scrollIntoView: true })
        view.focus()
        return
      }
      const ta = taRef.current?.resizableTextArea?.textArea
      if (ta) {
        ta.focus()
        ta.setSelectionRange(start, end)
      }
    },
    focus: () => {
      viewRef.current?.focus()
      taRef.current?.resizableTextArea?.textArea?.focus()
    },
    revealOffset: offset => {
      const view = viewRef.current
      if (view) {
        const pos = Math.max(0, Math.min(offset, view.state.doc.length))
        view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
        view.focus()
        return
      }
      const ta = taRef.current?.resizableTextArea?.textArea
      if (ta) {
        ta.focus()
        ta.setSelectionRange(offset, offset)
        const line = ta.value.slice(0, offset).split('\n').length
        ta.scrollTop = Math.max(0, (line - 3) * 24)
      }
    },
  }), [])

  // 受控同步：外部（草稿加载、工具栏写入、撤销）改变 value 时同步进编辑器
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const current = view.state.doc.toString()
    if (current !== value) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } })
    }
  }, [value, mode])

  // 实时预览：CodeMirror 实例随模式挂载/卸载
  useEffect(() => {
    if (mode !== 'live' || !hostRef.current) return
    const state = EditorState.create({
      doc: value,
      extensions: [
        history(),
        drawSelection(),
        EditorView.lineWrapping,
        markdown({ base: markdownLanguage }),
        livePreviewPlugin,
        imageContext.of(workspaceId),
        cmPlaceholder(placeholder ?? ''),
        EditorView.updateListener.of(update => {
          if (update.docChanged) onChangeRef.current(update.state.doc.toString())
          if (update.docChanged || update.selectionSet) {
            onCaretRef.current?.(update.state.selection.main.head)
          }
        }),
        EditorView.domEventHandlers({
          paste(event) {
            const items = event.clipboardData?.items
            if (!items) return false
            const files: File[] = []
            for (const item of Array.from(items)) {
              if (item.kind === 'file' && item.type.startsWith('image/')) {
                const file = item.getAsFile()
                if (file) files.push(file)
              }
            }
            if (files.length === 0) return false
            event.preventDefault()
            for (const file of files) onPasteRef.current?.([file])
            return true
          },
        }),
        keymap.of([
          { key: 'Escape', run: () => { onShortcutRef.current?.('escape'); return true } },
          { key: 'Mod-f', run: () => { onShortcutRef.current?.('find'); return true } },
          { key: 'Mod-h', run: () => { onShortcutRef.current?.('find'); return true } },
          { key: 'Mod-b', run: () => { onShortcutRef.current?.('bold'); return true } },
          { key: 'Mod-i', run: () => { onShortcutRef.current?.('italic'); return true } },
          { key: 'Mod-k', run: () => { onShortcutRef.current?.('link'); return true } },
          indentWithTab,
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        editorTheme,
      ],
    })
    const view = new EditorView({ state, parent: hostRef.current })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
    // value/placeholder 只在挂载时取初值；后续通过受控同步 effect 写入。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, workspaceId])

  if (mode === 'source') {
    return (
      <Input.TextArea
        ref={taRef}
        value={value}
        onChange={e => onChange(e.target.value)}
        onSelect={e => onCaret?.((e.target as HTMLTextAreaElement).selectionStart)}
        onClick={e => onCaret?.((e.target as HTMLTextAreaElement).selectionStart)}
        onPaste={e => {
          const items = e.clipboardData?.items
          if (!items) return
          const files: File[] = []
          for (const item of Array.from(items)) {
            if (item.kind === 'file' && item.type.startsWith('image/')) {
              const file = item.getAsFile()
              if (file) files.push(file)
            }
          }
          if (files.length === 0) return
          e.preventDefault()
          onPasteImages?.(files)
        }}
        onKeyDown={e => {
          if (e.key === 'Escape') {
            onShortcut?.('escape')
            return
          }
          if (!(e.ctrlKey || e.metaKey) || e.altKey) return
          const key = e.key.toLowerCase()
          if (key === 'f' || key === 'h') {
            e.preventDefault()
            onShortcut?.('find')
          } else if (key === 'b') {
            e.preventDefault()
            onShortcut?.('bold')
          } else if (key === 'i') {
            e.preventDefault()
            onShortcut?.('italic')
          } else if (key === 'k') {
            e.preventDefault()
            onShortcut?.('link')
          }
        }}
        placeholder={placeholder}
        style={{
          flex: 1,
          minHeight: 0,
          resize: 'none',
          border: 'none',
          boxShadow: 'none',
          borderRadius: 0,
          fontFamily: 'var(--cn-mono, monospace)',
          fontSize: 14,
          lineHeight: 1.7,
          padding: 16,
          ...style,
        }}
      />
    )
  }

  return <div ref={hostRef} data-testid="doc-live-editor" style={{ ...EDITOR_STYLE, ...style }} />
})

export default MarkdownLiveEditor

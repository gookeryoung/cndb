/** Obsidian 风格 Markdown 编辑器：实时预览（隐藏语法标记 + 渲染元素）与源码双模式.
 *
 * 设计要点：
 * - **实时预览**用 CodeMirror 6 + `@codemirror/lang-markdown`，基于语法树给可见范围
 *   加装饰：语法标记（`#` / `**` / `` ` `` / 链接符号）在光标离开该元素时隐藏，
 *   标题、加粗、斜体、行内代码、引用、代码块、分隔线、图片按渲染态显示；
 *   光标进入对应元素后自动还原为源码，便于精确编辑（与 Obsidian 一致）。
 * - **源码模式**保留原生 textarea：行为与旧编辑器完全一致（查找替换、快捷键
 *   都基于字符偏移），也便于无障碍与输入法。
 * - 两种模式共用一套命令式句柄（选区 / 定位 / 聚焦），上层无需感知实现差异。
 */

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import type { CSSProperties } from 'react'
import { EditorState, Facet, StateField, type Range } from '@codemirror/state'
import {
  Decoration,
  type DecorationSet,
  EditorView,
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
import { highlightCode } from './codeHighlight'
import { parseImageRef } from './imageRef'
import { parseMdTable, type MdTable, type MdTableAlign } from './mdTable'
import { WEIGHT } from '@/theme/tokens'

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

// ── 待办复选框：点击写回 `[ ]` ↔ `[x]` ────────────────

class MarkdownTaskWidget extends WidgetType {
  constructor(
    private readonly checked: boolean,
    private readonly from: number,
    private readonly to: number,
    private readonly onToggle: (from: number, to: number, checked: boolean) => void,
  ) {
    super()
  }

  /** 位置变化也要重建：否则点击时会用旧偏移改错文本 */
  eq(other: MarkdownTaskWidget): boolean {
    return other.checked === this.checked && other.from === this.from && other.to === this.to
  }

  toDOM(): HTMLElement {
    const box = document.createElement('input')
    box.type = 'checkbox'
    box.className = 'cm-md-task'
    box.checked = this.checked
    // 阻止 CodeMirror 把 mousedown 当选区操作（否则光标落点错乱）
    box.addEventListener('mousedown', e => e.preventDefault())
    box.addEventListener('click', e => {
      e.preventDefault()
      this.onToggle(this.from, this.to, !this.checked)
    })
    return box
  }

  ignoreEvent(): boolean {
    return false
  }
}

// ── 无序列表符号：源码的 `-` / `*` / `+` 渲染成圆点 ─────────

class MarkdownBulletWidget extends WidgetType {
  constructor(private readonly glyph: string) {
    super()
  }

  eq(other: MarkdownBulletWidget): boolean {
    return other.glyph === this.glyph
  }

  toDOM(): HTMLElement {
    const span = document.createElement('span')
    span.className = 'cm-md-bullet'
    span.textContent = this.glyph
    return span
  }
}

// ── 表格：光标不在表格内时整块渲染成 <table> ────────────────

const INLINE_TOKEN_RE = /(\*\*|__)(.+?)\1|(\*|_)(.+?)\3|`([^`]+)`|~~(.+?)~~/g

/** 单元格内的行内语法（粗体 / 斜体 / 行内代码 / 删除线）渲染成 DOM */
function appendInlineMarkdown(parent: HTMLElement, text: string): void {
  let last = 0
  INLINE_TOKEN_RE.lastIndex = 0
  for (let m = INLINE_TOKEN_RE.exec(text); m; m = INLINE_TOKEN_RE.exec(text)) {
    if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)))
    if (m[2] !== undefined) {
      const strong = document.createElement('strong')
      strong.textContent = m[2]
      parent.appendChild(strong)
    } else if (m[4] !== undefined) {
      const em = document.createElement('em')
      em.textContent = m[4]
      parent.appendChild(em)
    } else if (m[5] !== undefined) {
      const code = document.createElement('code')
      code.textContent = m[5]
      parent.appendChild(code)
    } else {
      const del = document.createElement('del')
      del.textContent = m[6]
      parent.appendChild(del)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)))
}

function alignStyle(align: MdTableAlign): string {
  return align ? `text-align:${align}` : ''
}

class MarkdownTableWidget extends WidgetType {
  constructor(
    private readonly table: MdTable,
    /** 位置 + 内容签名：任一变化都重建，保证 onEnter 闭包里的偏移是新的 */
    private readonly key: string,
    private readonly onEnter: () => void,
  ) {
    super()
  }

  eq(other: MarkdownTableWidget): boolean {
    return other.key === this.key
  }

  toDOM(): HTMLElement {
    const wrap = document.createElement('div')
    wrap.className = 'cm-md-table'
    // 点击渲染结果 → 光标落进表格首行，切回源码编辑（与 Obsidian 一致）
    wrap.addEventListener('mousedown', e => {
      e.preventDefault()
      this.onEnter()
    })

    const table = document.createElement('table')
    const thead = document.createElement('thead')
    const headRow = document.createElement('tr')
    this.table.header.forEach((cell, i) => {
      const th = document.createElement('th')
      th.style.cssText = alignStyle(this.table.align[i])
      appendInlineMarkdown(th, cell)
      headRow.appendChild(th)
    })
    thead.appendChild(headRow)
    table.appendChild(thead)

    const tbody = document.createElement('tbody')
    for (const row of this.table.rows) {
      const tr = document.createElement('tr')
      row.forEach((cell, i) => {
        const td = document.createElement('td')
        td.style.cssText = alignStyle(this.table.align[i])
        appendInlineMarkdown(td, cell)
        tr.appendChild(td)
      })
      tbody.appendChild(tr)
    }
    table.appendChild(tbody)
    wrap.appendChild(table)
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
/** 单块代码超过该长度不做词法高亮：避免超长贴入后每次按键全量 tokenize */
const MAX_HIGHLIGHT_CHARS = 100_000
/** 单次重建的词法高亮总预算：超出后其余代码块按纯文本显示，保证大文档按键不卡 */
const HIGHLIGHT_BUDGET_CHARS = 300_000

function hide(from: number, to: number): Range<Decoration> | null {
  return to > from ? Decoration.replace({}).range(from, to) : null
}

/** 构建装饰：语法标记隐藏 + 元素样式 + 图片 / 分隔线 / 表格 / 待办渲染.
 *
 * 表格要整块换成 <table>（块级替换），而 CodeMirror 不允许插件下发块装饰，
 * 因此装饰改由 StateField 提供；`getView` 只在 widget 交互（点击 / 勾选）时用来派发事务。
 */
function buildDecorations(state: EditorState, getView: () => EditorView | null): DecorationSet {
  const ranges: Range<Decoration>[] = []
  const doc = state.doc
  const cursor = state.selection.main.head
  const active = (from: number, to: number) => cursor >= from && cursor <= to
  const push = (deco: Range<Decoration> | null) => {
    if (deco) ranges.push(deco)
  }
  /** 勾选待办：只改标记本身（`[ ]` ↔ `[x]`），其余字符不动 */
  const toggleTask = (from: number, to: number, checked: boolean) => {
    getView()?.dispatch({ changes: { from, to, insert: checked ? '[x]' : '[ ]' } })
  }
  let highlightBudget = HIGHLIGHT_BUDGET_CHARS

  syntaxTree(state).iterate({
    enter: node => {
      const name = node.name
      const nodeActive = active(node.from, node.to)
      const heading = HEADING_RE.exec(name)
      if (heading) {
        const level = heading[1]
        ranges.push(
          Decoration.line({ class: `cm-md-heading cm-md-h${level}` }).range(doc.lineAt(node.from).from),
        )
        if (!nodeActive) {
          for (const mark of node.node.getChildren('HeaderMark')) {
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
              widget: new MarkdownImageWidget(parsed[2], parsed[1], state.facet(imageContext)),
            }).range(node.from, node.to),
          )
        }
        return
      }

      if (name === 'HorizontalRule') {
        ranges.push(Decoration.line({ class: 'cm-md-hr' }).range(doc.lineAt(node.from).from))
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
        const fenced = name === 'FencedCode'
        const firstLine = doc.lineAt(node.from)
        const lastLine = doc.lineAt(node.to)
        // 闭合围栏行：与首行同为 ``` / ~~~ 且不是同一行（空代码块）
        const closing =
          fenced && lastLine.number > firstLine.number && /^\s*(?:`{3,}|~{3,})\s*$/.test(lastLine.text)
        const contentFrom = fenced ? Math.min(firstLine.to + 1, doc.length) : node.from
        const contentTo = closing ? lastLine.from : node.to

        ranges.push(Decoration.line({ class: 'cm-md-codefence' }).range(firstLine.from))
        if (closing) ranges.push(Decoration.line({ class: 'cm-md-codefence' }).range(lastLine.from))

        if (contentTo > contentFrom) {
          for (let pos = contentFrom; pos < contentTo; ) {
            const line = doc.lineAt(pos)
            ranges.push(Decoration.line({ class: 'cm-md-codeblock' }).range(line.from))
            if (line.to >= contentTo) break
            pos = line.to + 1
          }
          // 词法高亮：与预览共用 codeHighlight，围栏语言取自 CodeInfo（```ts）
          const code = doc.sliceString(contentFrom, contentTo)
          if (code.length <= MAX_HIGHLIGHT_CHARS && highlightBudget >= code.length) {
            highlightBudget -= code.length
            const info = node.node.getChild('CodeInfo')
            const language = info ? doc.sliceString(info.from, info.to) : null
            for (const token of highlightCode(code, language)) {
              ranges.push(
                Decoration.mark({ class: `cn-tok-${token.type}` }).range(
                  contentFrom + token.from,
                  contentFrom + token.to,
                ),
              )
            }
          }
        }
        return
      }

      if (name === 'Table') {
        // 顶层表格才整块替换（引用 / 列表内的表格保留源码，避免块装饰与行装饰冲突）
        const topLevel = node.node.parent?.name === 'Document'
        if (nodeActive || !topLevel) return
        const firstLine = doc.lineAt(node.from)
        const lastLine = doc.lineAt(node.to)
        if (lastLine.from < firstLine.from) return
        const parsed = parseMdTable(doc.sliceString(firstLine.from, lastLine.to))
        if (!parsed) return
        const anchor = Math.min(firstLine.from + 1, doc.length)
        ranges.push(
          Decoration.replace({
            block: true,
            widget: new MarkdownTableWidget(parsed, `${firstLine.from}:${lastLine.to}`, () => {
              const view = getView()
              if (!view) return
              view.dispatch({ selection: { anchor }, scrollIntoView: true })
              view.focus()
            }),
          }).range(firstLine.from, lastLine.to),
        )
        // 单元格已随整块替换隐藏，不必再下发内部装饰
        return false
      }

      if (name === 'Task') {
        const marker = node.node.getChild('TaskMarker')
        if (!marker || nodeActive) return
        const checked = /\[[xX]\]/.test(doc.sliceString(marker.from, marker.to))
        ranges.push(
          Decoration.replace({
            widget: new MarkdownTaskWidget(checked, marker.from, marker.to, toggleTask),
          }).range(marker.from, marker.to),
        )
        return
      }

      if (name === 'ListMark') {
        const mark = doc.sliceString(node.from, node.to)
        if (/^[-*+]$/.test(mark)) {
          // 无序列表：`-` 换成圆点，按缩进层级换符号；顺带吃掉标记后的空格
          const indent = node.from - doc.lineAt(node.from).from
          const glyph = ['•', '◦', '▪'][Math.floor(indent / 2) % 3]
          const end = doc.sliceString(node.to, node.to + 1) === ' ' ? node.to + 1 : node.to
          ranges.push(Decoration.replace({ widget: new MarkdownBulletWidget(glyph) }).range(node.from, end))
          return
        }
        // 有序列表保留序号，只做配色
        ranges.push(Decoration.mark({ class: 'cm-md-listmark' }).range(node.from, node.to))
      }
    },
  })

  return Decoration.set(ranges, true)
}

/** 图片组件需要工作区上下文：用 facet 传递给 widget（widget 无法使用 React hook） */
const imageContext = Facet.define<number | string | undefined, number | string | undefined>({
  combine: values => values[values.length - 1],
})

/** 实时预览装饰的 StateField：块级装饰（表格）只能由 state 提供，插件不允许 */
function livePreviewField(getView: () => EditorView | null) {
  return StateField.define<DecorationSet>({
    create: state => buildDecorations(state, getView),
    update: (decos, tr) =>
      tr.docChanged || tr.selection ? buildDecorations(tr.state, getView) : decos,
    provide: field => EditorView.decorations.from(field),
  })
}

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
    backgroundColor: 'var(--cn-mix-brand-color-22-transparent)',
  },
  '.cm-placeholder': { color: 'var(--cn-text-muted, #9ca3af)' },
  '.cm-md-heading': { fontWeight: WEIGHT.bold, lineHeight: '1.4' },
  '.cm-md-h1': { fontSize: '1.75em' },
  '.cm-md-h2': { fontSize: '1.45em' },
  '.cm-md-h3': { fontSize: '1.25em' },
  '.cm-md-h4': { fontSize: '1.1em' },
  '.cm-md-h5': { fontSize: '1em' },
  '.cm-md-h6': { fontSize: '0.95em', color: 'var(--cn-text-secondary, #6b7280)' },
  '.cm-md-em': { fontStyle: 'italic' },
  '.cm-md-strong': { fontWeight: WEIGHT.bold },
  '.cm-md-strike': { textDecoration: 'line-through' },
  '.cm-md-code': {
    fontFamily: 'var(--cn-font-mono)',
    backgroundColor: 'var(--cn-bg-subtle, #fafafa)',
    borderRadius: '4px',
    padding: '1px 4px',
    fontSize: '0.92em',
  },
  '.cm-md-link': { color: 'var(--cn-brand-color, #1677ff)', textDecoration: 'underline' },
  '.cm-md-listmark': { color: 'var(--cn-brand-color, #1677ff)' },
  '.cm-md-bullet': {
    display: 'inline-block',
    width: '0.9em',
    color: 'var(--cn-brand-color, #1677ff)',
    fontWeight: WEIGHT.bold,
  },
  '.cm-md-task': {
    marginRight: '4px',
    verticalAlign: 'middle',
    cursor: 'pointer',
    accentColor: 'var(--cn-brand-color, #1677ff)',
  },
  '.cm-md-table': { padding: '2px 0 8px', overflowX: 'auto', cursor: 'text' },
  '.cm-md-table table': {
    borderCollapse: 'collapse',
    width: '100%',
    fontSize: '13px',
    lineHeight: '1.6',
  },
  '.cm-md-table th, .cm-md-table td': {
    border: '1px solid var(--cn-border, #e5e7eb)',
    padding: '5px 10px',
    verticalAlign: 'top',
  },
  '.cm-md-table th': { background: 'var(--cn-bg-subtle, #fafafa)', fontWeight: WEIGHT.semibold },
  '.cm-md-table code': {
    fontFamily: 'var(--cn-font-mono)',
    background: 'var(--cn-bg-subtle, #fafafa)',
    borderRadius: '3px',
    padding: '1px 3px',
  },
  '.cm-md-quote': {
    borderLeft: '3px solid var(--cn-border, #e5e7eb)',
    paddingLeft: '12px',
    color: 'var(--cn-text-secondary, #6b7280)',
  },
  '.cm-md-hr': { borderTop: '1px solid var(--cn-border, #e5e7eb)' },
  '.cm-md-codeblock': {
    fontFamily: 'var(--cn-font-mono)',
    backgroundColor: 'var(--cn-code-block-bg, #f6f8fa)',
    borderLeft: '3px solid var(--cn-code-block-border, #d0d7de)',
    paddingLeft: 'var(--cn-space-lg, 12px)',
    fontSize: '0.92em',
  },
  '.cm-md-codefence': {
    fontFamily: 'var(--cn-font-mono)',
    color: 'var(--cn-text-muted, #9ca3af)',
    fontSize: '0.85em',
  },
  '.cm-md-image': { display: 'inline-flex', alignItems: 'center', maxWidth: '100%' },
  '.cm-md-image img': { maxWidth: '100%', maxHeight: '320px', borderRadius: '6px', verticalAlign: 'middle' },
})

const EDITOR_STYLE: CSSProperties = { flex: 1, minHeight: 0, overflow: 'hidden' }

const MarkdownLiveEditor = forwardRef<MarkdownEditorHandle, MarkdownLiveEditorProps>(function MarkdownLiveEditor(
  { value, mode, workspaceId, placeholder, onChange, onPasteImages, onShortcut, style },
  ref,
) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const taRef = useRef<TextAreaRef>(null)

  // 用 ref 持有回调，避免父组件每次渲染都重建 EditorView（丢撤销栈与光标）
  const onChangeRef = useRef(onChange)
  const onPasteRef = useRef(onPasteImages)
  const onShortcutRef = useRef(onShortcut)
  useEffect(() => {
    onChangeRef.current = onChange
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
        livePreviewField(() => viewRef.current),
        imageContext.of(workspaceId),
        cmPlaceholder(placeholder ?? ''),
        EditorView.updateListener.of(update => {
          if (update.docChanged) onChangeRef.current(update.state.doc.toString())
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
          fontFamily: 'var(--cn-font-mono)',
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

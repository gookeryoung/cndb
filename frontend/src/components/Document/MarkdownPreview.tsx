/** Markdown 预览组件 — react-markdown + GFM + 代码块样式 + 数据表动态引用渲染.

标题元素渲染锚点 id（与大纲面板解析同算法），支持大纲点击定位。
*/

import { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import TableEmbed from './TableEmbed'
import { splitTableRefs } from './tableRef'
import { headingAnchor } from './outline'

/** React 子节点提取纯文本（生成标题锚点用） */
function childrenToText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (Array.isArray(children)) return children.map(childrenToText).join('')
  return ''
}

/** Markdown 渲染组件配置（代码块/引用/原生表格样式），整体与分片渲染共用 */
const mdComponents = {
  h1: ({ children, ...rest }: React.ComponentProps<'h1'>) => (
    <h1
      id={headingAnchor(childrenToText(children))}
      style={{ fontSize: '1.6em', margin: '0.8em 0 0.4em' }}
      {...rest}
    >
      {children}
    </h1>
  ),
  h2: ({ children, ...rest }: React.ComponentProps<'h2'>) => (
    <h2
      id={headingAnchor(childrenToText(children))}
      style={{ fontSize: '1.4em', margin: '0.8em 0 0.4em' }}
      {...rest}
    >
      {children}
    </h2>
  ),
  h3: ({ children, ...rest }: React.ComponentProps<'h3'>) => (
    <h3
      id={headingAnchor(childrenToText(children))}
      style={{ fontSize: '1.2em', margin: '0.7em 0 0.4em' }}
      {...rest}
    >
      {children}
    </h3>
  ),
  h4: ({ children, ...rest }: React.ComponentProps<'h4'>) => (
    <h4 id={headingAnchor(childrenToText(children))} {...rest}>
      {children}
    </h4>
  ),
  h5: ({ children, ...rest }: React.ComponentProps<'h5'>) => (
    <h5 id={headingAnchor(childrenToText(children))} {...rest}>
      {children}
    </h5>
  ),
  h6: ({ children, ...rest }: React.ComponentProps<'h6'>) => (
    <h6 id={headingAnchor(childrenToText(children))} {...rest}>
      {children}
    </h6>
  ),
  code: ({ className, children, ...rest }: React.ComponentProps<'code'> & { className?: string }) => {
    const isBlock = /language-/.test(className ?? '') || String(children).includes('\n')
    if (isBlock) {
      return (
        <code
          className={className}
          style={{
            display: 'block',
            padding: 12,
            background: 'var(--cn-bg-secondary, #f6f6f6)',
            borderRadius: 8,
            overflowX: 'auto',
            fontSize: 13,
            fontFamily: 'var(--cn-mono, monospace)',
          }}
          {...rest}
        >
          {children}
        </code>
      )
    }
    return (
      <code
        style={{
          background: 'var(--cn-bg-secondary, #f0f0f0)',
          padding: '2px 6px',
          borderRadius: 4,
          fontSize: '0.9em',
          fontFamily: 'var(--cn-mono, monospace)',
        }}
        {...rest}
      >
        {children}
      </code>
    )
  },
  blockquote: (props: React.ComponentProps<'blockquote'>) => (
    <blockquote
      style={{
        margin: '0.8em 0',
        padding: '4px 16px',
        borderLeft: '4px solid var(--cn-border-strong, #d0d0d0)',
        color: 'var(--cn-text-secondary, #666)',
      }}
      {...props}
    />
  ),
  table: (props: React.ComponentProps<'table'>) => (
    <table
      style={{
        borderCollapse: 'collapse',
        margin: '0.8em 0',
        width: '100%',
        fontSize: 13,
      }}
      {...props}
    />
  ),
  th: (props: React.ComponentProps<'th'>) => (
    <th
      style={{ border: '1px solid var(--cn-border, #e0e0e0)', padding: '6px 12px', background: 'var(--cn-bg-secondary, #fafafa)' }}
      {...props}
    />
  ),
  td: (props: React.ComponentProps<'td'>) => (
    <td style={{ border: '1px solid var(--cn-border, #e0e0e0)', padding: '6px 12px' }} {...props} />
  ),
} as const

/** Markdown 片段渲染 */
function Md({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
      {text}
    </ReactMarkdown>
  )
}

function MarkdownPreviewBase({ content, workspaceId }: {
  content: string
  /** 工作区 ID：提供后启用 `{{table:…}}` 数据表动态引用渲染 */
  workspaceId?: number
}) {
  const segments = useMemo(
    () => (workspaceId !== undefined ? splitTableRefs(content) : null),
    [content, workspaceId],
  )
  const hasTableRef = segments?.some(s => s.type === 'table') ?? false

  // 无工作区上下文或无引用片段：整体按 Markdown 渲染
  if (!hasTableRef) {
    return (
      <div className="doc-md-preview" style={{ lineHeight: 1.75, wordBreak: 'break-word' }}>
        <Md text={content} />
      </div>
    )
  }

  return (
    <div className="doc-md-preview" style={{ lineHeight: 1.75, wordBreak: 'break-word' }}>
      {segments!.map((seg, i) =>
        seg.type === 'md' ? (
          <Md key={i} text={seg.text} />
        ) : (
          <TableEmbed key={i} workspaceId={workspaceId!} tableRef={seg.ref} />
        ),
      )}
    </div>
  )
}

const MarkdownPreview = memo(MarkdownPreviewBase)
export default MarkdownPreview

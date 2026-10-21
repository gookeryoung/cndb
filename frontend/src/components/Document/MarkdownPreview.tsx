/** Markdown 预览组件 — react-markdown + GFM + 代码块样式 + 数据表动态引用渲染 +
 * 双向链接（[[文档标题]]）渲染为可点击跳转.
 *
 * 标题元素渲染锚点 id（与大纲面板解析同算法），支持大纲点击定位。
 */

import { memo, useMemo } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import CodeBlock from './CodeBlock'
import DocumentImage from './DocumentImage'
import { FILE_REF_PREFIX } from './imageRef'
import remarkGfm from 'remark-gfm'
import TableEmbed from './TableEmbed'
import { splitTableRefs } from './tableRef'
import { headingAnchor } from './outline'
import { scrollToHeading } from './docAnchor'
import { parseWikilinkHref, transformWikilinks } from './wikilink'

/** React 子节点提取纯文本（生成标题锚点用） */
function childrenToText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (Array.isArray(children)) return children.map(childrenToText).join('')
  return ''
}

/** Markdown 渲染组件配置（代码块/引用/原生表格样式），整体与分片渲染共用 */
/** react-markdown 传入的 hast 节点（只用到 children/tagName 结构） */
type MarkdownNode = {
  type?: string
  tagName?: string
  children?: MarkdownNode[]
}

/** 段落是否只包含图片（用于避免 div 嵌在 p 内的非法嵌套） */
function isImageOnlyParagraph(node?: MarkdownNode): boolean {
  const children = (node?.children ?? []).filter(
    (c) => !(c.type === 'text' && !(c as { value?: string }).value?.trim()),
  )
  if (children.length !== 1) return false
  const only = children[0]
  if (only.tagName === 'img') return true
  // 形如 [![alt](file:x)](url)：链接里包一张图片
  return only.tagName === 'a' && (only.children ?? []).some((c) => c.tagName === 'img')
}

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
    const raw = String(children)
    const isBlock = /language-/.test(className ?? '') || raw.includes('\n')
    if (isBlock) {
      // 围栏代码块交给 CodeBlock：语言标签 + 复制按钮 + 词法高亮
      const language = /language-([\w+#.-]+)/.exec(className ?? '')?.[1] ?? null
      return <CodeBlock code={raw} language={language} />
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
  // `pre` 默认会包住上面的代码块，形成 <pre><div> 的非法嵌套；
  // 直接透传子节点，块级容器由 CodeBlock 自己提供
  pre: ({ children }: React.ComponentProps<'pre'>) => <>{children}</>,
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

/** Markdown 片段渲染（双链 [[标题]] 预转换为链接，a 组件拦截前缀回调跳转） */
function Md({
  text,
  workspaceId,
  onWikilink,
}: {
  text: string
  workspaceId?: number | string
  onWikilink?: (title: string) => void
}) {
  const components = useMemo(
    () => ({
      ...mdComponents,
      // 站内图片 `![alt](file:<key>)` 需带鉴权取 blob；外部 URL 原样渲染
      img: ({ src, alt }: React.ComponentProps<'img'>) => (
        <DocumentImage workspaceId={workspaceId} src={src} alt={alt} />
      ),
      // 仅含图片的段落用 div 承载：antd Image 的根元素是 div，
      // 放在 Markdown 的 <p> 里会产生非法嵌套（React 报
      // "validateDOMNesting(...): <div> cannot appear as a descendant of <p>"，
      // 浏览器还会把 <p> 提前闭合，导致图片脱离段落排版）。
      p: ({ children, node }: React.ComponentProps<'p'> & { node?: MarkdownNode }) => {
        const onlyImage = isImageOnlyParagraph(node)
        return onlyImage
          ? <div style={{ margin: '0.6em 0' }}>{children}</div>
          : <p>{children}</p>
      },
      a: ({ href, children, ...rest }: React.ComponentProps<'a'>) => {
        const title = href != null ? parseWikilinkHref(href) : null
        if (title === null) {
          // 文内锚点（目录 `[小节](#小节)` / `[[#小节]]`）：预览区原地滚动，
          // 不走浏览器 hash 跳转（SPA 下改 hash 会污染路由且找不到 doc-h-* 前缀的 id）
          if (href?.startsWith('#') && href.length > 1) {
            return (
              <a
                href={href}
                data-testid="doc-anchor-link"
                style={{ color: 'var(--cn-primary, #1890ff)', cursor: 'pointer' }}
                {...rest}
                onClick={e => {
                  e.preventDefault()
                  scrollToHeading(href)
                }}
              >
                {children}
              </a>
            )
          }
          return <a href={href} {...rest}>{children}</a>
        }
        return (
          <a
            href={href}
            data-testid="doc-wikilink"
            style={{ color: 'var(--cn-primary, #1890ff)', cursor: 'pointer' }}
            onClick={e => {
              e.preventDefault()
              onWikilink?.(title)
            }}
            {...rest}
          >
            {children}
          </a>
        )
      },
    }),
    [onWikilink, workspaceId],
  )
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={components}
      // react-markdown 默认只放行 http/https/mailto 等协议，会剥离自定义的 `file:`；
      // 站内图片引用必须原样保留，交给 DocumentImage 用带鉴权的请求取 blob
      urlTransform={url => (url.startsWith(FILE_REF_PREFIX) ? url : defaultUrlTransform(url))}
    >
      {transformWikilinks(text)}
    </ReactMarkdown>
  )
}

function MarkdownPreviewBase({ content, workspaceId, onWikilink }: {
  content: string
  /** 工作区 ID：提供后启用 `{{table:…}}` 数据表动态引用渲染 */
  workspaceId?: number
  /** 双向链接点击回调：入参为 [[文档标题]] 中的标题 */
  onWikilink?: (title: string) => void
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
        <Md text={content} workspaceId={workspaceId} onWikilink={onWikilink} />
      </div>
    )
  }

  return (
    <div className="doc-md-preview" style={{ lineHeight: 1.75, wordBreak: 'break-word' }}>
      {segments!.map((seg, i) =>
        seg.type === 'md' ? (
          <Md key={i} text={seg.text} workspaceId={workspaceId} onWikilink={onWikilink} />
        ) : (
          <TableEmbed key={i} workspaceId={workspaceId!} tableRef={seg.ref} />
        ),
      )}
    </div>
  )
}

const MarkdownPreview = memo(MarkdownPreviewBase)
export default MarkdownPreview

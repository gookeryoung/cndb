/** Markdown 预览组件 — react-markdown + GFM + 代码块样式 + 数据表 / 图表动态引用渲染 +
 * 双向链接（[[文档标题]]）渲染为可点击跳转.
 *
 * 标题元素渲染锚点 id（与大纲面板解析同算法），支持大纲点击定位。
 */

// react-markdown / hast 依赖链使用 Object.hasOwn（Chrome 93+），在懒加载 chunk 内补齐
import '@/compat/polyfills'
import { memo, useMemo } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import CodeBlock from './CodeBlock'
import DocumentImage from './DocumentImage'
import { FILE_REF_PREFIX } from './imageRef'
import remarkGfm from 'remark-gfm'
import TableEmbed from './TableEmbed'
import ChartEmbed from './ChartEmbed'
import { splitRefs } from './refs'
import type { ChartBlockSpec } from './chartBlock'
import type { RefWidthChange } from './refWidth'
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
          background: 'var(--cn-bg-subtle, #f0f0f0)',
          border: '1px solid var(--cn-border, transparent)',
          padding: '2px 6px',
          borderRadius: 4,
          fontSize: '0.9em',
          fontFamily: 'var(--cn-font-mono)',
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
        borderLeft: '4px solid var(--cn-border, #d0d0d0)',
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
      style={{
        border: '1px solid var(--cn-border, #e0e0e0)',
        padding: '6px 12px',
        background: 'var(--cn-bg-subtle, #fafafa)',
        color: 'var(--cn-text-primary, #1f2937)',
      }}
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
  publicFileBase,
  onWikilink,
}: {
  text: string
  workspaceId?: number | string
  /** 公开分享页的免登录图片基地址（提供后站内图片直接走公开 URL） */
  publicFileBase?: string
  onWikilink?: (title: string) => void
}) {
  const components = useMemo(
    () => ({
      ...mdComponents,
      // 站内图片 `![alt](file:<key>)` 需带鉴权取 blob；外部 URL 原样渲染
      img: ({ src, alt }: React.ComponentProps<'img'>) => (
        <DocumentImage workspaceId={workspaceId} publicFileBase={publicFileBase} src={src} alt={alt} />
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
    [onWikilink, workspaceId, publicFileBase],
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

function MarkdownPreviewBase({ content, workspaceId, shareToken, publicFileBase, onWikilink, onEditChart, onRefWidthChange, onChartWidthChange }: {
  content: string
  /** 工作区 ID：提供后启用 `{{table:…}}` 动态引用与图表块渲染 */
  workspaceId?: number
  /** 游客分享 token（ADR 0052 D10）：提供后启用图表块免登录渲染；数据表引用维持不渲染 */
  shareToken?: string
  /** 公开分享页的免登录图片基地址（ADR 0017） */
  publicFileBase?: string
  /** 双向链接点击回调：入参为 [[文档标题]] 中的标题 */
  onWikilink?: (title: string) => void
  /** 图表编辑入口（写权限由页面侧判断后传入）；不传时 ChartEmbed 无编辑按钮 */
  onEditChart?: (spec: ChartBlockSpec, occurrence: number) => void
  /** 数据表引用宽度调整回调（ADR 0051；写权限由页面侧判断后传入） */
  onRefWidthChange?: (change: RefWidthChange) => void
  /** 图表块宽度调整回调（ADR 0052 D8：宽度写入正文块） */
  onChartWidthChange?: (occurrence: number, width: number) => void
}) {
  // 游客分享模式：无工作区上下文但带分享 token，只切 chart 片段（table 占位维持文本）
  const publicMode = workspaceId === undefined && shareToken !== undefined
  const segments = useMemo(
    () =>
      workspaceId !== undefined || publicMode
        ? splitRefs(content, { chartsOnly: publicMode })
        : null,
    [content, workspaceId, publicMode],
  )
  const hasRef = segments?.some(s => s.type !== 'md') ?? false

  // 无工作区上下文或无引用片段：整体按 Markdown 渲染
  if (!hasRef) {
    return (
      <div className="doc-md-preview" style={{ lineHeight: 1.75, wordBreak: 'break-word' }}>
        <Md text={content} workspaceId={workspaceId} publicFileBase={publicFileBase} onWikilink={onWikilink} />
      </div>
    )
  }

  return (
    <div className="doc-md-preview" style={{ lineHeight: 1.75, wordBreak: 'break-word' }}>
      {(() => {
        // 同一定义可被多次插入：图表按出现序号定位（宽度 / 编辑），数据表仍按 ID 计数
        const ordinals = new Map<string, number>()
        const nextOrdinal = (key: string) => {
          const n = ordinals.get(key) ?? 0
          ordinals.set(key, n + 1)
          return n
        }
        return segments!.map((seg, i) => {
          if (seg.type === 'md') {
            return (
              <Md key={i} text={seg.text} workspaceId={workspaceId} publicFileBase={publicFileBase} onWikilink={onWikilink} />
            )
          }
          if (seg.type === 'table') {
            const occurrence = nextOrdinal(`table:${seg.ref.tableId}`)
            return (
              <TableEmbed
                key={i}
                workspaceId={workspaceId!}
                tableRef={seg.ref}
                refOrdinal={occurrence}
                onWidthChange={onRefWidthChange
                  ? w => onRefWidthChange({
                    kind: 'table',
                    id: seg.ref.tableId,
                    occurrence,
                    width: w,
                  })
                  : undefined}
              />
            )
          }
          const occurrence = nextOrdinal('chart')
          return (
            <ChartEmbed
              key={i}
              workspaceId={workspaceId}
              shareToken={shareToken}
              block={seg.block}
              width={seg.block.spec?.width}
              refOrdinal={occurrence}
              onEditChart={onEditChart}
              onWidthChange={onChartWidthChange
                ? w => onChartWidthChange(occurrence, w)
                : undefined}
            />
          )
        })
      })()}
    </div>
  )
}

const MarkdownPreview = memo(MarkdownPreviewBase)
export default MarkdownPreview

/** Markdown 预览组件 — react-markdown + GFM + 代码块样式. */

import { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function MarkdownPreviewBase({ content }: { content: string }) {
  const md = useMemo(() => content, [content])
  return (
    <div className="doc-md-preview" style={{ lineHeight: 1.75, wordBreak: 'break-word' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: props => <h1 style={{ fontSize: '1.6em', margin: '0.8em 0 0.4em' }} {...props} />,
          h2: props => <h2 style={{ fontSize: '1.4em', margin: '0.8em 0 0.4em' }} {...props} />,
          h3: props => <h3 style={{ fontSize: '1.2em', margin: '0.7em 0 0.4em' }} {...props} />,
          code: ({ className, children, ...rest }) => {
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
          blockquote: props => (
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
          table: props => (
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
          th: props => (
            <th
              style={{ border: '1px solid var(--cn-border, #e0e0e0)', padding: '6px 12px', background: 'var(--cn-bg-secondary, #fafafa)' }}
              {...props}
            />
          ),
          td: props => (
            <td style={{ border: '1px solid var(--cn-border, #e0e0e0)', padding: '6px 12px' }} {...props} />
          ),
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  )
}

const MarkdownPreview = memo(MarkdownPreviewBase)
export default MarkdownPreview

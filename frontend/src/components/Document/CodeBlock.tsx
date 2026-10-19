/** 文档预览里的代码块：语言标签 + 复制按钮 + 词法高亮。
 *
 * 高亮由 `codeHighlight.ts` 提供（零依赖），颜色走 index.css 的 `--cn-code-*`
 * 主题变量，浅色 / 深色主题自动切换。未知语言只渲染纯文本，不猜语法。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { highlightCode, languageLabel, normalizeLanguage } from './codeHighlight'
import type { CodeToken } from './codeHighlight'

interface CodeBlockProps {
  /** 代码原文（fence 内容，含结尾换行） */
  code: string
  /** fence info 里的语言标识，如 `ts` / `python` / `language-sql` */
  language?: string | null
}

/** 复制成功后的「已复制」提示保持时长 */
const COPIED_MS = 1500

/** 非安全上下文（http）下 clipboard API 不可用，退回 textarea + execCommand */
function fallbackCopy(text: string): boolean {
  if (typeof document.execCommand !== 'function') return false
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.top = '-9999px'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 权限被拒 / 非安全上下文：走兜底
  }
  return fallbackCopy(text)
}

/** token 序列 → React 节点（未覆盖的区间按纯文本渲染） */
function renderTokens(code: string, tokens: CodeToken[]): ReactNode[] {
  const nodes: ReactNode[] = []
  let cursor = 0
  tokens.forEach((token, index) => {
    if (token.from > cursor) nodes.push(code.slice(cursor, token.from))
    nodes.push(
      <span key={index} className={`cn-tok-${token.type}`}>
        {code.slice(token.from, token.to)}
      </span>,
    )
    cursor = token.to
  })
  if (cursor < code.length) nodes.push(code.slice(cursor))
  return nodes
}

export default function CodeBlock({ code, language }: CodeBlockProps) {
  const text = useMemo(() => code.replace(/\n$/, ''), [code])
  const lang = useMemo(() => normalizeLanguage(language), [language])
  const label = useMemo(() => languageLabel(language), [language])
  const tokens = useMemo(() => highlightCode(text, lang), [text, lang])
  const nodes = useMemo(() => renderTokens(text, tokens), [text, tokens])

  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    [],
  )

  const handleCopy = async () => {
    if (!(await copyText(text))) return
    setCopied(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setCopied(false), COPIED_MS)
  }

  return (
    <div className="cn-codeblock" data-testid="cn-codeblock">
      <div className="cn-codeblock-head">
        <span className="cn-codeblock-lang">{label ?? '代码'}</span>
        <span className="cn-codeblock-meta">
          {text ? `${text.split('\n').length} 行` : '空'}
        </span>
        <button
          type="button"
          className="cn-codeblock-copy"
          aria-label="复制代码"
          title="复制代码"
          onClick={handleCopy}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
          <span>{copied ? '已复制' : '复制'}</span>
        </button>
      </div>
      <pre className="cn-codeblock-pre">
        <code className={`language-${lang ?? 'text'}`}>{nodes}</code>
      </pre>
    </div>
  )
}

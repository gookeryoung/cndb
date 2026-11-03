/** Office 原件预览（后端生成的自包含 HTML）内联渲染.
 *
 * 为什么不用 iframe：iframe 自带一个独立视口，正文区会多出一条「内层滚动条」，
 * 且与页面主题割裂（深色下像一块单独的黑底预览区）。这里把后端 HTML 拆成
 * 「样式 + body 片段」放进 **Shadow DOM**：
 * - 样式被影子根隔离，不会污染页面（后端 CSS 用 `body` / `table` 等通用选择器）；
 * - 内容随页面流动，滚动交给文档页正文区（与 PPTX 预览同一模型）；
 * - 不执行脚本：后端 HTML 由模板拼接且来源文本全部转义，这里再兜底剔除 `<script>`；
 *   需要真沙箱的 MHTML（外部网页存档）仍走 iframe。
 */

import { useEffect, useRef } from 'react'

const SCRIPT_BLOCK_RE = /<script\b[\s\S]*?<\/script>/gi

/** 影子根基础样式：后端 CSS 里的 `body` 规则在影子根中不生效，这里补宿主字体与前景色.
 * 颜色统一走页面主题变量（自定义属性会继承进影子根），与所在主题保持一致。 */
const HOST_BASE_CSS = `
:host { display: block; font: 14px/1.7 -apple-system, "Segoe UI", "Noto Sans SC", sans-serif;
  color: var(--cn-text-primary, #1f2937); background: transparent; }
`

export interface PreviewFragment {
  /** 后端 HTML 里的全部 `<style>` 文本 */
  css: string
  /** `<body>` 内的标记（已剔除脚本） */
  body: string
}

/** 把后端自包含 HTML 拆成可在 Shadow DOM 内渲染的样式 + 片段. */
export function splitPreviewHtml(raw: string): PreviewFragment {
  if (typeof DOMParser === 'undefined') {
    return { css: '', body: raw.replace(SCRIPT_BLOCK_RE, '') }
  }
  const doc = new DOMParser().parseFromString(raw, 'text/html')
  const css = Array.from(doc.querySelectorAll('style'))
    .map(node => node.textContent ?? '')
    .join('\n')
  const body = doc.body?.innerHTML ?? ''
  return {
    css: css.replace(SCRIPT_BLOCK_RE, ''),
    body: body.replace(SCRIPT_BLOCK_RE, ''),
  }
}

interface Props {
  /** 后端预览端点返回的完整 HTML 文本 */
  html: string
}

export default function OfficeHtmlPreview({ html }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const { css, body } = splitPreviewHtml(html)
    const root = host.shadowRoot ?? host.attachShadow({ mode: 'open' })
    root.innerHTML = `<style>${HOST_BASE_CSS}${css}</style>${body}`
  }, [html])

  return (
    <div
      ref={hostRef}
      data-testid="doc-asset-office"
      // 与 PPTX 预览同一模型：内容区唯一滚动容器（宽表横向滚动也在这里）
      style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '4px 0 12px' }}
    />
  )
}

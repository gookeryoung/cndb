/**
 * 双向链接（[[文档标题]]）预处理：把正文中的双链语法转换为 Markdown 链接，
 * 由 MarkdownPreview 的 a 组件拦截 `#wikilink:` 前缀渲染为可点击跳转。
 * 代码围栏内的 [[...]] 视为字面文本，不参与转换。
 */

const WIKILINK_RE = /\[\[([^[\]]+)\]\]/g
const FENCE_RE = /^\s*(```|~~~)/

/** 双链转换后链接 href 的统一前缀（a 组件按此识别） */
export const WIKILINK_HREF_PREFIX = '#wikilink:'

/** 正文中的 [[标题]] 替换为 Markdown 链接（标题 encodeURIComponent 编码进 href） */
function replaceLine(line: string): string {
  return line.replace(WIKILINK_RE, (raw, title: string) => {
    const t = title.trim()
    if (!t) return raw // 空白标题（如 [[ ]]）按原文本保留
    return `[${t}](${WIKILINK_HREF_PREFIX}${encodeURIComponent(t)})`
  })
}

/** 全文双链转换：跳过 ``` / ~~~ 代码围栏行 */
export function transformWikilinks(content: string): string {
  const lines = content.split('\n')
  let inFence = false
  const out = lines.map(line => {
    if (FENCE_RE.test(line)) {
      inFence = !inFence
      return line
    }
    if (inFence) return line
    return replaceLine(line)
  })
  return out.join('\n')
}

/** 解析双链 href：非双链前缀返回 null，否则返回解码后的文档标题 */
export function parseWikilinkHref(href: string): string | null {
  if (!href.startsWith(WIKILINK_HREF_PREFIX)) return null
  try {
    return decodeURIComponent(href.slice(WIKILINK_HREF_PREFIX.length))
  } catch {
    return null
  }
}

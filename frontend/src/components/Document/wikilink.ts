/**
 * 双向链接（[[标题]] / [[标题#锚点]] / [[标题|别名]]）预处理：
 * 把双链语法转换为 Markdown 链接，由 MarkdownPreview 的 a 组件拦截
 * `#wikilink:` 前缀渲染为可点击跳转。代码围栏内的 [[...]] 视为字面文本，不参与转换。
 *
 * 三种成分的分工（对齐后端 `parse.parse_wikilink`）：
 * - target：跳转依据（站内按标题匹配；库内路径前缀已在导入时剥掉）；
 * - anchor：无别名时显示为「标题 › 锚点」，跳转仍落在文档首屏（站内暂无标题级锚点路由）；
 * - alias：有别名时**只显示别名**，与原库阅读观感一致。
 */

const WIKILINK_RE = /\[\[([^[\]]+)\]\]/g
const FENCE_RE = /^\s*(```|~~~)/

/** 双链转换后链接 href 的统一前缀（a 组件按此识别） */
export const WIKILINK_HREF_PREFIX = '#wikilink:'

export interface WikilinkParts {
  /** 跳转目标（文档标题）；空串表示本文内锚点 [[#标题]] */
  target: string
  /** 锚点（# 之后、| 之前），可为空 */
  anchor: string
  /** 别名（| 之后），可为空 */
  alias: string
}

/** 解析双链内层文本：`目标#锚点|别名`（三段都可缺省） */
export function parseWikilinkInner(inner: string): WikilinkParts {
  const text = inner.trim()
  const pipeAt = text.indexOf('|')
  const body = pipeAt >= 0 ? text.slice(0, pipeAt) : text
  const alias = pipeAt >= 0 ? text.slice(pipeAt + 1).trim() : ''
  const hashAt = body.indexOf('#')
  const target = (hashAt >= 0 ? body.slice(0, hashAt) : body).trim()
  const anchor = hashAt >= 0 ? body.slice(hashAt + 1).trim() : ''
  return { target, anchor, alias }
}

/** 展示文本：别名优先；无别名时带锚点后缀，让读者知道指向哪一节 */
export function wikilinkLabel(parts: WikilinkParts): string {
  if (parts.alias) return parts.alias
  if (parts.anchor) return `${parts.target} › ${parts.anchor}`
  return parts.target
}

/** 正文中的双链替换为 Markdown 链接（目标标题 encodeURIComponent 编码进 href） */
function replaceLine(line: string): string {
  return line.replace(WIKILINK_RE, (raw, inner: string) => {
    const parts = parseWikilinkInner(inner)
    if (!parts.target) {
      // [[#本文锚点]]：站内没有本文锚点表达，按纯文本保留（去掉 # 更好读）
      return parts.anchor || raw
    }
    return `[${wikilinkLabel(parts)}](${WIKILINK_HREF_PREFIX}${encodeURIComponent(parts.target)})`
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

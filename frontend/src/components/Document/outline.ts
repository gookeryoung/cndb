/** 文档大纲 — 标题解析与锚点生成（大纲面板与预览锚点共用）. */

/** 大纲条目：标题级别 / 文本 / 锚点 id / 所在行（0 起） */
export interface OutlineItem {
  level: number
  text: string
  anchor: string
  line: number
}

/**
 * 标题文本生成预览区锚点 id（与 MarkdownPreview 标题元素 id 同算法）。
 *
 * 算法：小写 → 去除字母数字空白连字符以外的字符 → 空白折叠为连字符；
 * 保留 Unicode 字母数字（中文标题可用）。
 */
export function headingAnchor(text: string): string {
  const slug = text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s+/g, '-')
  return `doc-h-${slug || 'empty'}`
}

/**
 * 从 Markdown 正文实时解析 ATX 标题（`#` 至 `######`）。
 *
 * 代码围栏（``` / ~~~）内的井号行不计；Setext 下划线标题不解析（简化，编辑场景统一 ATX）。
 */
export function parseOutline(content: string): OutlineItem[] {
  const items: OutlineItem[] = []
  let inFence = false
  const lines = content.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (/^\s{0,3}(```|~~~)/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue
    const m = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line)
    if (m) {
      items.push({ level: m[1].length, text: m[2], anchor: headingAnchor(m[2]), line: i })
    }
  }
  return items
}

/** 搜索命中高亮片段：按 `<mark>` 标记切片（避免整段 HTML 注入） */
export function parseHitHighlight(hit: string): Array<{ text: string; marked: boolean }> {
  const parts: Array<{ text: string; marked: boolean }> = []
  let marked = false
  for (const seg of hit.split(/(<\/?mark>)/)) {
    if (seg === '<mark>') {
      marked = true
    } else if (seg === '</mark>') {
      marked = false
    } else if (seg) {
      parts.push({ text: seg, marked })
    }
  }
  return parts
}

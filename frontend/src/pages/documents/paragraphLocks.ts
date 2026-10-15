/** 段落定位工具 —— 与后端 `services/paragraph_lock.py` 的切分规则保持一致.
 *
 * 段落 = Markdown 块级单元（按**空行**切分，段内保留换行）。段落键为位置键 `p1` / `p2` …
 * 与后端同一约定：键基于**已保存版本**的位置，因此"同一段"始终是同一把锁。
 */

/** 按空行切分段落（与后端 split_paragraphs 一致：去首尾空白、忽略空块） */
export function splitParagraphs(text: string): string[] {
  if (!text || !text.trim()) return []
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split(/\n\s*\n/)
    .map((part) => part.replace(/^\n+|\n+$/g, ''))
    .filter((part) => part.trim().length > 0)
}

export function paragraphKeys(text: string): string[] {
  return splitParagraphs(text).map((_, i) => `p${i + 1}`)
}

/** 把光标偏移换算成段落序号（1 基）；空文本或非法偏移返回 null */
export function paragraphIndexAtOffset(text: string, offset: number): number | null {
  if (!text || offset < 0) return null
  let cursor = 0
  const parts = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split(/\n\s*\n/)
  for (let i = 0; i < parts.length; i++) {
    const start = cursor
    const end = cursor + parts[i].length
    if (offset >= start && offset <= end) {
      return parts[i].trim().length > 0 ? i + 1 : null
    }
    cursor = end + 2 // 空行分隔符
  }
  // 落在末尾空行之后 → 归属最后一段
  const total = splitParagraphs(text).length
  return total > 0 ? total : null
}

/** 段落序号 → 该段在文本中的起始偏移（用于"跳转到冲突段落"） */
export function offsetOfParagraph(text: string, index: number): number | null {
  if (index < 1) return null
  let cursor = 0
  let seen = 0
  const parts = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split(/\n\s*\n/)
  for (const part of parts) {
    if (!part.trim()) {
      cursor += part.length + 2
      continue
    }
    seen += 1
    if (seen === index) return cursor
    cursor += part.length + 2
  }
  return null
}

export function keyToIndex(key: string): number | null {
  if (!key.startsWith('p')) return null
  const tail = key.slice(1)
  return /^\d+$/.test(tail) && Number(tail) > 0 ? Number(tail) : null
}

/** 文档预览内的标题锚点定位 —— 目录链接（`[小节](#小节)`）/ 本文锚点（`[[#小节]]`）
 * 与大纲抽屉共用同一套解析，点击后滚动到预览区对应标题。
 *
 * 目录链接的 `#` 后面可能是标题原文（`#安装指南`）、URL 编码文本或已生成的
 * 锚点 id（`#doc-h-安装指南`），统一在这里归一。
 */

import { headingAnchor } from './outline'

/** 预览区标题选择器（与 MarkdownPreview 渲染的 h1~h6 对应） */
const HEADING_SELECTOR = 'h1, h2, h3, h4, h5, h6'
/** 标题锚点 id 前缀（与 outline.headingAnchor 一致） */
const ANCHOR_PREFIX = 'doc-h-'

function safeDecode(raw: string): string {
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** 去掉可能已带上的锚点前缀，避免二次 slug 生成 `doc-h-doc-h-…` */
function bare(text: string): string {
  return text.startsWith(ANCHOR_PREFIX) ? text.slice(ANCHOR_PREFIX.length) : text
}

/**
 * 按锚点查找预览区标题元素（入参可带 `#`）。
 *
 * 命中顺序：锚点 id 精确匹配 → 标题文本生成的 id（`doc-h-…`）→
 * 同文本标题兜底（链接里省略了标点 / 大小写不一致时）。
 */
export function findHeadingElement(anchor: string): HTMLElement | null {
  const raw = anchor.replace(/^#/, '').trim()
  if (!raw) return null
  const text = safeDecode(raw)
  const target = bare(text)
  const candidates = [text, `${ANCHOR_PREFIX}${bare(target)}`, headingAnchor(target)]
  for (const id of candidates) {
    const hit = document.getElementById(id)
    if (hit) return hit
  }
  // 兜底：按标题文本匹配（`[一、概述](#一概述)` 这类省略标点的目录写法）
  const headings = Array.from(document.querySelectorAll<HTMLElement>(HEADING_SELECTOR))
  const normalized = headingAnchor(target)
  return (
    headings.find(el => (el.textContent ?? '').trim() === target) ??
    headings.find(el => headingAnchor((el.textContent ?? '').trim()) === normalized) ??
    null
  )
}

/** 滚动到标题锚点；命中返回 true（未命中由调用方决定提示 / 忽略） */
export function scrollToHeading(anchor: string): boolean {
  const el = findHeadingElement(anchor)
  if (!el) return false
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  return true
}

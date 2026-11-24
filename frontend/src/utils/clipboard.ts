/** 剪贴板复制（文档预览代码块与帮助示例共用）.
 *
 * 先走 Clipboard API；局域网 http 部署属于非安全上下文，API 不可用或权限被拒时
 * 退回 textarea + execCommand —— Chrome 81 基线下这是唯一可用的兜底。
 *
 * 唯一入口：任何「复制到剪贴板」的功能都必须走 `copyText`，不要直接调
 * `navigator.clipboard`——局域网 http（如 `http://192.168.1.10:8080`）下
 * `navigator.clipboard` 为 `undefined`，直调会抛 TypeError 变成「复制失败」。
 */

/** 复制成功后「已复制」提示的保持时长（毫秒） */
export const COPIED_MS = 1500

/** 非安全上下文（http）下 clipboard API 不可用，退回 textarea + execCommand */
function fallbackCopy(text: string): boolean {
  if (typeof document.execCommand !== 'function') return false
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.setAttribute('aria-hidden', 'true')
  // 固定在视口内但不可见：非安全上下文里位置在视口外的选区可能不被复制
  area.style.position = 'fixed'
  area.style.top = '0'
  area.style.left = '0'
  area.style.width = '1px'
  area.style.height = '1px'
  area.style.padding = '0'
  area.style.border = 'none'
  area.style.opacity = '0'
  area.style.pointerEvents = 'none'
  document.body.appendChild(area)
  try {
    area.focus({ preventScroll: true })
    area.select()
    // 部分内核（Safari / 旧 Chrome）只认 setSelectionRange 建立的选区
    area.setSelectionRange?.(0, text.length)
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}

/** 复制文本；返回是否成功（失败时调用方不应提示「已复制」）。 */
export async function copyText(text: string): Promise<boolean> {
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

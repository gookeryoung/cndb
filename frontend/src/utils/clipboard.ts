/** 剪贴板复制（文档预览代码块与帮助示例共用）.
 *
 * 先走 Clipboard API；局域网 http 部署属于非安全上下文，API 不可用或权限被拒时
 * 退回 textarea + execCommand —— Chrome 81 基线下这是唯一可用的兜底。
 */

/** 复制成功后「已复制」提示的保持时长（毫秒） */
export const COPIED_MS = 1500

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

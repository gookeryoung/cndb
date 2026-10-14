/** 字节数 → 人类可读体积. */

/**
 * 字节数格式化为 B / KB / MB。
 *
 * @param bytes 字节数
 * @param fractionDigits 小数位（默认 1；管理面板的后端产物清单用 2 位）
 */
export function formatSize(bytes: number, fractionDigits = 1): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(fractionDigits)} KB`
  return `${(bytes / 1024 / 1024).toFixed(fractionDigits)} MB`
}

/** 从 Content-Disposition 头解析下载文件名.
 *
 * 优先级：filename*=UTF-8''...（RFC 5987 编码，支持中文）> filename="..."（ASCII fallback）。
 * 找不到或解码失败返回 null。后端导出端点统一通过该头下发建议文件名。
 */
export function parseContentDispositionFilename(header: string | undefined): string | null {
  if (!header) return null
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim())
    } catch {
      // 解码失败 fall through 到 filename
    }
  }
  const quotedMatch = header.match(/filename="?([^";]+)"?/i)
  if (quotedMatch?.[1]) return quotedMatch[1].trim()
  return null
}

/** 文档内图片引用 —— 纯函数层.
 *
 * 引用形式：``![alt](file:<file_key>)``。与既有 ``[[wikilink]]`` 一样属于**应用内引用**：
 * 后端 `GET /workspaces/{wid}/files/{file_key}` 要求 Bearer 鉴权，而 `<img src>` 无法携带
 * 自定义请求头，因此预览/导出侧统一把 file_key 交给 `useFileObjectUrl` 取 blob 再渲染。
 * 好处：markdown 里不泄露工作区 id（文档在工作区内复制仍可用），且显式区分「站内文件」与外部 URL。
 */

/** 站内文件引用的协议前缀 */
export const FILE_REF_PREFIX = 'file:'

/** 图片扩展名白名单（与后端 `_ALLOWED_EXTENSIONS` 中的图片部分保持一致） */
export const IMAGE_EXTENSIONS: readonly string[] = [
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico', '.tiff',
]

/** 文件名中的 markdown 特殊字符做最小转义，避免图片语法被截断 */
function sanitizeAlt(filename: string): string {
  return filename.replace(/[[\]]/g, '').replace(/\s+/g, ' ').trim() || '图片'
}

/** 构造图片 markdown 片段 */
export function buildImageSnippet(filename: string, fileKey: string): string {
  return `![${sanitizeAlt(filename)}](${FILE_REF_PREFIX}${fileKey})`
}

/** 解析站内文件引用：返回 file_key；外部 URL / data: / 空值返回 null */
export function parseImageRef(src?: string | null): string | null {
  if (!src || !src.startsWith(FILE_REF_PREFIX)) return null
  const key = src.slice(FILE_REF_PREFIX.length).trim()
  return key || null
}

/** 是否为可插入的图片文件（按 MIME 判断，缺失时回退扩展名判断） */
export function isImageFile(file: { type?: string; name?: string }): boolean {
  if (file.type) return file.type.startsWith('image/')
  const name = (file.name ?? '').toLowerCase()
  return IMAGE_EXTENSIONS.some(ext => name.endsWith(ext))
}

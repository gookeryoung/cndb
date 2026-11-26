/** 内容模板的文件格式（导入 / 导出，ADR 0177 C5）.
 *
 * 与导出模板文件（`templateFile.ts`，`kind=cndb-document-template`）**互不兼容**：
 * 内容模板只搬「名称 / 说明 / 图标 / 正文骨架」，不含任何排版参数；把排版模板文件
 * 拖到内容模板页会得到明确提示，而不是静默当成空模板导入。
 *
 * 单文件同样支持一条或多条：导出单个模板时 `templates` 只有一项。
 * 只搬内容，不带 id / sort_order / 工作区 —— 归属与顺序由导入端决定。
 */

export const CONTENT_TEMPLATE_FILE_KIND = 'cndb-content-template'
export const CONTENT_TEMPLATE_FILE_VERSION = 1
/** 排版模板文件（`templateFile.ts`）的 kind：用于给出「传错页面」的明确提示 */
export const EXPORT_TEMPLATE_FILE_KIND = 'cndb-document-template'

export interface ContentTemplateFileEntry {
  name: string
  description?: string
  icon?: string
  content_markdown: string
}

export interface ContentTemplateFile {
  kind: string
  version: number
  exported_at?: string
  templates: ContentTemplateFileEntry[]
}

/** 构造可下载的模板文件对象（`exported_at` 仅作留档，导入时不使用） */
export function buildContentTemplateFile(entries: ContentTemplateFileEntry[]): ContentTemplateFile {
  return {
    kind: CONTENT_TEMPLATE_FILE_KIND,
    version: CONTENT_TEMPLATE_FILE_VERSION,
    exported_at: new Date().toISOString(),
    templates: entries,
  }
}

/** 序列化为带缩进的 JSON 文本（对 diff / 人工阅读友好） */
export function contentTemplateFileText(entries: ContentTemplateFileEntry[]): string {
  return `${JSON.stringify(buildContentTemplateFile(entries), null, 2)}\n`
}

/** 文件名：`内容模板-<名称>-<YYYYMMDD>.json`，去掉文件系统非法字符 */
export function contentTemplateFileName(name: string, all = false): string {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const safe = (all ? '全部模板' : name || '模板').replace(/[\\/:*?"<>|]/g, '_')
  return `内容模板-${safe}-${stamp}.json`
}

/** 解析导入文件；格式不合法时抛出可直接展示的中文错误 */
export function parseContentTemplateFile(text: string): ContentTemplateFileEntry[] {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    throw new Error('不是合法的 JSON 文件')
  }
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('模板文件内容为空或格式不正确')
  }
  const data = raw as Partial<ContentTemplateFile> & { templates?: unknown }
  if (data.kind === EXPORT_TEMPLATE_FILE_KIND) {
    throw new Error('这是导出模板文件（Word / PDF 排版），请到「导出模板」页导入')
  }
  if (data.kind !== undefined && data.kind !== CONTENT_TEMPLATE_FILE_KIND) {
    throw new Error('不是晶格协同的内容模板文件')
  }
  if (data.version !== undefined && Number(data.version) > CONTENT_TEMPLATE_FILE_VERSION) {
    throw new Error(`模板文件版本过新（v${String(data.version)}），请升级程序后再导入`)
  }
  const list = Array.isArray(data.templates) ? data.templates : [data]
  const entries: ContentTemplateFileEntry[] = []
  list.forEach((item, index) => {
    if (typeof item !== 'object' || item === null) {
      throw new Error(`第 ${index + 1} 条模板格式不正确`)
    }
    const entry = item as Partial<ContentTemplateFileEntry>
    const name = typeof entry.name === 'string' ? entry.name.trim() : ''
    if (!name) throw new Error(`第 ${index + 1} 条模板缺少名称`)
    if (entry.content_markdown !== undefined && typeof entry.content_markdown !== 'string') {
      throw new Error(`模板「${name}」的正文（content_markdown）必须是文本`)
    }
    entries.push({
      name,
      description: typeof entry.description === 'string' ? entry.description : '',
      icon: typeof entry.icon === 'string' ? entry.icon : '',
      content_markdown: typeof entry.content_markdown === 'string' ? entry.content_markdown : '',
    })
  })
  if (entries.length === 0) throw new Error('模板文件里没有任何模板')
  return entries
}

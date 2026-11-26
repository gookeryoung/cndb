/** 导出模板的文件格式（导入 / 导出，ADR 0152）.
 *
 * 单文件同时承载「一个或多个模板」：导出单个模板时 `templates` 只有一项，
 * 导出全部时有多项；导入两种都能吃。带 `kind` / `version` 便于将来演进格式，
 * 版本不认识直接拒绝（不静默丢字段）。
 *
 * 只搬**排版配置**，不带 id / is_default / 工作区：模板归属由导入端的工作区决定。
 */

import type { ExportTemplateConfig } from '@/api'

export const TEMPLATE_FILE_KIND = 'cndb-document-template'
export const TEMPLATE_FILE_VERSION = 1
/** 导入时名称去重的后缀（第 1 次「（导入）」，之后「（导入 2）」…） */
const IMPORT_SUFFIX = '（导入）'

export interface TemplateFileEntry {
  name: string
  description?: string
  config: ExportTemplateConfig
}

export interface TemplateFile {
  kind: string
  version: number
  exported_at?: string
  templates: TemplateFileEntry[]
}

/** 构造可下载的模板文件对象（`exported_at` 仅作留档，导入时不使用） */
export function buildTemplateFile(entries: TemplateFileEntry[]): TemplateFile {
  return {
    kind: TEMPLATE_FILE_KIND,
    version: TEMPLATE_FILE_VERSION,
    exported_at: new Date().toISOString(),
    templates: entries,
  }
}

/** 序列化为带缩进的 JSON 文本（对 diff / 人工阅读友好） */
export function templateFileText(entries: TemplateFileEntry[]): string {
  return `${JSON.stringify(buildTemplateFile(entries), null, 2)}\n`
}

/** 文件名：`文档模板-<名称>-<YYYYMMDD>.json`，去掉文件系统非法字符 */
export function templateFileName(name: string, all = false): string {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const safe = (all ? '全部模板' : name || '模板').replace(/[\\/:*?"<>|]/g, '_')
  return `文档模板-${safe}-${stamp}.json`
}

/** 解析导入文件；格式不合法时抛出可直接展示的中文错误 */
export function parseTemplateFile(text: string): TemplateFileEntry[] {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    throw new Error('不是合法的 JSON 文件')
  }
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('模板文件内容为空或格式不正确')
  }
  const data = raw as Partial<TemplateFile> & { templates?: unknown }
  if (data.kind !== undefined && data.kind !== TEMPLATE_FILE_KIND) {
    throw new Error('不是晶格协同的文档模板文件')
  }
  if (data.version !== undefined && Number(data.version) > TEMPLATE_FILE_VERSION) {
    throw new Error(`模板文件版本过新（v${String(data.version)}），请升级程序后再导入`)
  }
  const list = Array.isArray(data.templates) ? data.templates : [data]
  const entries: TemplateFileEntry[] = []
  list.forEach((item, index) => {
    if (typeof item !== 'object' || item === null) {
      throw new Error(`第 ${index + 1} 条模板格式不正确`)
    }
    const entry = item as Partial<TemplateFileEntry>
    const name = typeof entry.name === 'string' ? entry.name.trim() : ''
    if (!name) throw new Error(`第 ${index + 1} 条模板缺少名称`)
    if (typeof entry.config !== 'object' || entry.config === null) {
      throw new Error(`模板「${name}」缺少配置（config）`)
    }
    entries.push({
      name,
      description: typeof entry.description === 'string' ? entry.description : '',
      config: entry.config as ExportTemplateConfig,
    })
  })
  if (entries.length === 0) throw new Error('模板文件里没有任何模板')
  return entries
}

/** 导入时的名称去重：同名依次尝试「（导入）」「（导入 2）」… */
export function suggestImportName(name: string, existing: Set<string>): string {
  if (!existing.has(name)) return name
  const base = name
  let candidate = `${base}${IMPORT_SUFFIX}`
  let counter = 2
  while (existing.has(candidate)) {
    candidate = `${base}（导入 ${counter}）`
    counter += 1
  }
  return candidate
}

/** 读取用户选择的文本文件（FileReader 兼容旧内核；读取失败给出中文错误） */
export function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsText(file)
  })
}

/** 导出格式偏好 —— 默认 XLSX，并记住上次选择（localStorage 单键，跨表 / 跨会话复用）.
 *
 * 归一化失败（未写过 / 脏值 / 存储不可用）一律回退 XLSX；格式偏好不应阻断导出。
 */

export type ExportFormat = 'xlsx' | 'csv' | 'json' | 'pdf'

/** 偏好键：与文档并排查看等偏好同属 `cndb_*` 命名空间 */
export const EXPORT_FORMAT_KEY = 'cndb_export_format'

/** 用户从未选过格式时的默认值 */
export const DEFAULT_EXPORT_FORMAT: ExportFormat = 'xlsx'

const EXPORT_FORMATS: readonly ExportFormat[] = ['xlsx', 'csv', 'json', 'pdf']

/** 读取上次选择；未写过 / 非法值 / 存储不可用回退默认 XLSX */
export function loadExportFormat(): ExportFormat {
  try {
    const raw = localStorage.getItem(EXPORT_FORMAT_KEY)
    return EXPORT_FORMATS.includes(raw as ExportFormat) ? (raw as ExportFormat) : DEFAULT_EXPORT_FORMAT
  } catch {
    return DEFAULT_EXPORT_FORMAT
  }
}

/** 记录本次选择（隐私模式 / 配额不足时静默失败） */
export function saveExportFormat(format: ExportFormat): void {
  try {
    localStorage.setItem(EXPORT_FORMAT_KEY, format)
  } catch {
    /* 偏好写入失败不影响导出 */
  }
}

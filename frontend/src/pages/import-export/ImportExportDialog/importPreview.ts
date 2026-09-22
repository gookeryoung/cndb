/** 导入预览纯逻辑 — 阶段常量 / 参考列推荐类型 / Diff 表格列构建.
 *
 * 从 ImportExportDialog 拆出：不依赖 React 渲染，便于单元测试与复用.
 */
import type { CSSProperties } from 'react'

/** 允许的导入文件扩展名 */
export const ACCEPTED_EXT = ['.csv', '.json', '.xlsx']

export type Phase = 'idle' | 'analyzing' | 'preview' | 'importing' | 'done' | 'failed'

/** 后端参考列推荐条目（validation_report.match_key_recommendations） */
export interface MatchKeyRecommendation {
  field: string
  field_type: string
  score: number
  recommended: boolean
  disabled: boolean
  reason: string
  stats: Record<string, number | null>
}

/** 把值格式化为可显示的短文本（超长截断） */
export function fmtValue(v: unknown, limit = 80): string {
  if (v == null) return ''
  const s = String(v)
  return s.length > limit ? s.slice(0, limit - 3) + '...' : s
}

/** 每行变更字段数 */
export function changedCountOf(row: { field_diffs?: Record<string, unknown> } | undefined): number {
  return row?.field_diffs ? Object.keys(row.field_diffs).length : 0
}

/** 字段级 diff 单元格样式基线（GitHub diff 风格 chip 共用） */
export function diffChipStyle(): Pick<CSSProperties, 'fontSize' | 'lineHeight' | 'padding' | 'borderRadius' | 'alignSelf' | 'maxWidth' | 'overflowWrap'> {
  return {
    fontSize: 12,
    lineHeight: '18px',
    padding: '0 6px',
    borderRadius: 3,
    alignSelf: 'flex-start',
    maxWidth: 280,
    overflowWrap: 'anywhere',
  }
}

export interface DiffColumnKeys {
  /** 参考列（match_key_values 出现过的字段名，按首行顺序） */
  kvKeys: string[]
  /** new 模式首行样本字段名 */
  sampleKeys: string[]
  /** update 模式出现字段差异的字段名 */
  diffKeys: string[]
  /** 三者按 kv → sample → diff 去重合并后的最终列序 */
  allFieldNames: string[]
}

/** 列名收集：new 模式沿用首行样本；update 模式跨全部行取并集并聚焦变化字段 */
export function collectDiffColumnKeys(
  preview: Array<Record<string, any>> | undefined,
  mode: 'new' | 'update',
): DiffColumnKeys {
  const isNew = mode === 'new'
  const kvKeys: string[] = []
  const sampleKeys: string[] = []
  const diffKeys: string[] = []
  if (isNew) {
    const firstRow = preview?.[0]
    Object.keys(firstRow?.match_key_values ?? {}).forEach(k => kvKeys.push(k))
    Object.keys(firstRow?.field_sample ?? {}).forEach(k => sampleKeys.push(k))
  } else {
    preview?.forEach(row => {
      Object.keys(row.match_key_values ?? {}).forEach(k => { if (!kvKeys.includes(k)) kvKeys.push(k) })
      Object.keys(row.field_diffs ?? {}).forEach(k => { if (!diffKeys.includes(k)) diffKeys.push(k) })
    })
  }
  const allFieldNames: string[] = []
  kvKeys.forEach(k => { if (!allFieldNames.includes(k)) allFieldNames.push(k) })
  sampleKeys.forEach(k => { if (!allFieldNames.includes(k)) allFieldNames.push(k) })
  diffKeys.forEach(k => { if (!allFieldNames.includes(k)) allFieldNames.push(k) })
  return { kvKeys, sampleKeys, diffKeys, allFieldNames }
}

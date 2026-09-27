/** 矩阵视图纯逻辑层 — 二维分组聚合（与 UI 解耦，可独立单测）.
 *
 * 职责：
 * - dateBucket：日期值按粒度分桶（year/quarter/month/week/day）
 * - axisKeyForRow：单行在某轴上的分组 key（select/link/multi_select 取标签，date 分桶，text 原样）
 * - buildMatrixGrid：行集合 → 行 key 序 × 列 key 序 × 单元格行列表
 *
 * 设计约定（见 .trae/designs/matrix-view.md）：
 * - 空值/解析失败统一归「未分组」，且「未分组」桶恒排在各轴末尾
 * - 日期桶 key 采用字典序==时序的格式（YYYY / YYYY-Qn / YYYY-MM / 周起始日 / YYYY-MM-DD），
 *   因此桶排序直接字符串比较即可
 * - 分类桶按 zh-CN localeCompare 升序
 */

import type { Field, RowResponse } from '@/api'
import dayjs from 'dayjs'
import { getLinkFirstLabel, getMultiSelectFirstLabel, getSelectLabel } from '../cells/fieldValueFormat'

// ── 常量与类型 ────────────────────────────────────────

/** 空值分组显示名（纵轴/横轴一致） */
export const UNGROUPED_LABEL = '未分组'

/** 日期轴分桶粒度 */
export type MatrixDateGranularity = 'year' | 'quarter' | 'month' | 'week' | 'day'

/** 单元格复合键：rowKey 与 colKey 以 :: 连接（分组值来自字段标签，可能含任意字符，:: 冲突概率可忽略） */
export function cellKey(rowKey: string, colKey: string): string {
  return `${rowKey}::${colKey}`
}

/** 周桶标题后缀：桶 key 为周起始日（周一）YYYY-MM-DD，标题补充「当周」说明 */
const WEEK_TITLE_SUFFIX = ' 当周'

// ── 日期分桶 ──────────────────────────────────────────

/** 日期值 → 分桶 key；空值或解析失败返回空串（调用方归「未分组」）.
 *
 * week 桶 key 取该周起始日（dayjs startOf('week')，跟随全局 locale）格式化为 YYYY-MM-DD，
 * 与其他粒度一样保持字典序==时序。
 */
export function dateBucket(value: unknown, granularity: MatrixDateGranularity): string {
  if (value === null || value === undefined || value === '') return ''
  const d = dayjs(String(value))
  if (!d.isValid()) return ''
  switch (granularity) {
    case 'year':
      return d.format('YYYY')
    case 'quarter':
      // dayjs core 无 quarter()（需 QuarterOfYear 插件），按月序自算：0-2 → Q1
      return `${d.format('YYYY')}-Q${Math.floor(d.month() / 3) + 1}`
    case 'week':
      return d.startOf('week').format('YYYY-MM-DD')
    case 'day':
      return d.format('YYYY-MM-DD')
    case 'month':
    default:
      return d.format('YYYY-MM')
  }
}

/** 分桶 key → 轴头显示标题（week 粒度补充「当周」，其余原样） */
export function bucketTitle(key: string, granularity: MatrixDateGranularity): string {
  return granularity === 'week' && key !== UNGROUPED_LABEL ? `${key}${WEEK_TITLE_SUFFIX}` : key
}

// ── 轴 key 求值 ───────────────────────────────────────

/** 计算单行在某轴上的分组 key；空值/解析失败返回空串（调用方归「未分组」）.
 *
 * 类型分派与看板 groupKeyForRow 对齐：link/multi_select 取首值标签，select 按字段
 * options 映射标签，date/datetime 按粒度分桶，text 及未知类型 String 化。
 */
export function axisKeyForRow(
  row: RowResponse,
  fieldDef: Field | undefined,
  granularity: MatrixDateGranularity,
): string {
  const fieldName = fieldDef?.name
  const rawVal = fieldName ? row[fieldName] : undefined
  if (fieldDef) {
    const ft = fieldDef.field_type
    if (ft === 'date' || ft === 'datetime') return dateBucket(rawVal, granularity)
    if (ft === 'link') return getLinkFirstLabel(rawVal)
    if (ft === 'multi_select' || ft === 'multiselect') return getMultiSelectFirstLabel(rawVal)
    if (ft === 'select') return getSelectLabel(fieldDef, rawVal)
  }
  if (rawVal === null || rawVal === undefined || rawVal === '') return ''
  return String(rawVal)
}

/** 判断轴字段是否为日期类（决定桶排序策略：时序 vs 字典序） */
export function isDateAxis(fieldDef: Field | undefined): boolean {
  return !!fieldDef && (fieldDef.field_type === 'date' || fieldDef.field_type === 'datetime')
}

/** 排序单轴 key 列表：日期轴按字典序（==时序）；分类轴按 zh-CN localeCompare；「未分组」恒最后 */
export function sortAxisKeys(keys: string[], dateAxis: boolean): string[] {
  const grouped = keys.filter((k) => k !== UNGROUPED_LABEL)
  const hasUngrouped = grouped.length !== keys.length
  if (dateAxis) {
    grouped.sort((a, b) => a.localeCompare(b))
  } else {
    grouped.sort((a, b) => a.localeCompare(b, 'zh-CN'))
  }
  if (hasUngrouped) grouped.push(UNGROUPED_LABEL)
  return grouped
}

// ── 网格构建 ──────────────────────────────────────────

/** 矩阵网格数据：行 key 序、列 key 序、单元格行集合 */
export interface MatrixGridData {
  /** 纵轴 key 列表（已排序，含「未分组」时在末尾） */
  rowKeys: string[]
  /** 横轴 key 列表（已排序，含「未分组」时在末尾） */
  columnKeys: string[]
  /** 单元格：复合键 → 该格内的行（保持 API 返回顺序） */
  cells: Map<string, RowResponse[]>
}

/** 构建矩阵网格：单次遍历 rows 完成二维分组，随后对各轴 key 排序 */
export function buildMatrixGrid(
  rows: RowResponse[],
  fields: Field[],
  rowField: string,
  columnField: string,
  granularity: MatrixDateGranularity,
): MatrixGridData {
  const rowDef = fields.find((f) => f.name === rowField)
  const colDef = fields.find((f) => f.name === columnField)

  const rowKeySet = new Set<string>()
  const colKeySet = new Set<string>()
  const cells = new Map<string, RowResponse[]>()

  for (const r of rows) {
    const rawRowKey = axisKeyForRow(r, rowDef, granularity)
    const rawColKey = axisKeyForRow(r, colDef, granularity)
    const rk = rawRowKey || UNGROUPED_LABEL
    const ck = rawColKey || UNGROUPED_LABEL
    rowKeySet.add(rk)
    colKeySet.add(ck)
    const key = cellKey(rk, ck)
    const bucket = cells.get(key)
    if (bucket) bucket.push(r)
    else cells.set(key, [r])
  }

  return {
    rowKeys: sortAxisKeys([...rowKeySet], isDateAxis(rowDef)),
    columnKeys: sortAxisKeys([...colKeySet], isDateAxis(colDef)),
    cells,
  }
}

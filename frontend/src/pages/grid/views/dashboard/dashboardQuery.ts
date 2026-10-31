/** dashboard 组件级查询的客户端执行（ADR 0023 P0）.
 *
 * dashboard 单表取数上限与其它非 grid 视图一致（2000 行），过滤/排序/截断在本地完成，
 * 与后端 SQL 口径保持同名操作符；P0 不做服务端聚合。
 */

import type { RowResponse } from '@/api'
import type { DashboardQuery } from './dashboardModel'

type Row = RowResponse

function isBlank(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim() === '')
}

function toNumber(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** 比较值大小：数值优先；否则按字符串比较；空值恒排后 */
function compareValues(a: unknown, b: unknown): number {
  if (isBlank(a) && isBlank(b)) return 0
  if (isBlank(a)) return 1
  if (isBlank(b)) return -1
  const na = toNumber(a)
  const nb = toNumber(b)
  if (na !== null && nb !== null) return na - nb
  return String(a).localeCompare(String(b), 'zh-Hans-CN')
}

/** 字符串/数组值统一为可比较文本 */
function asText(v: unknown): string {
  if (Array.isArray(v)) return v.map((x) => String(x)).join(',')
  return v == null ? '' : String(v)
}

function matches(row: Row, field: string, op: string, expected: unknown): boolean {
  const actual = row[field]
  const a = asText(actual)
  const e = asText(expected)
  switch (op) {
    case 'eq':
    case '=':
      return a === e
    case 'neq':
    case '!=':
      return a !== e
    case 'gt':
    case '>':
      return !isBlank(actual) && compareValues(actual, expected) > 0
    case 'gte':
    case '>=':
      return !isBlank(actual) && compareValues(actual, expected) >= 0
    case 'lt':
    case '<':
      return !isBlank(actual) && compareValues(actual, expected) < 0
    case 'lte':
    case '<=':
      return !isBlank(actual) && compareValues(actual, expected) <= 0
    case 'contains':
      return a.includes(e)
    case 'starts_with':
      return a.startsWith(e)
    case 'ends_with':
      return a.endsWith(e)
    case 'in':
      return Array.isArray(expected) && expected.map(asText).includes(a)
    case 'not_in':
      return Array.isArray(expected) && !expected.map(asText).includes(a)
    case 'is_empty':
    case 'is_null':
      return isBlank(actual)
    case 'is_not_empty':
    case 'is_not_null':
      return !isBlank(actual)
    case 'contains_any':
    case 'has_any':
      return Array.isArray(expected) && expected.map(asText).some((x) => a.includes(x))
    case 'contains_all':
    case 'has_all':
      return Array.isArray(expected) && expected.map(asText).every((x) => a.includes(x))
    case 'between':
    case 'date_range': {
      if (isBlank(actual)) return false
      if (!Array.isArray(expected) || expected.length < 2) return true
      const low = compareValues(actual, expected[0]) >= 0
      const high = compareValues(actual, expected[1]) <= 0
      return low && high
    }
    default:
      return true
  }
}

/** 执行组件级 filters / sortings / limit（不修改入参） */
export function applyWidgetQuery(rows: Row[], query: DashboardQuery): Row[] {
  let out = rows
  if (query.filters.length) {
    const check = (row: Row) => query.filters.map((f) => matches(row, f.field_name, f.op, f.value))
    out = out.filter((row) => {
      const results = check(row)
      return query.filter_logic === 'OR' ? results.some(Boolean) : results.every(Boolean)
    })
  }
  if (query.sortings.length) {
    out = [...out].sort((a, b) => {
      for (const s of query.sortings) {
        const av = a[s.field_name]
        const bv = b[s.field_name]
        // 空值恒排后，与升降序无关（对齐 SQL NULLS LAST 口径）
        if (isBlank(av) !== isBlank(bv)) return isBlank(av) ? 1 : -1
        const c = compareValues(av, bv)
        if (c !== 0) return s.direction === 'desc' ? -c : c
      }
      return 0
    })
  }
  if (query.limit != null) out = out.slice(0, query.limit)
  return out
}

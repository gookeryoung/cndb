/** 导入预览的纯转换逻辑 —— 单元格值按目标字段类型试转换.

从 FileImportPreview.tsx 抽出：不含任何 React/DOM 依赖，可独立单测。
*/

export interface CellTransform {
  /** 原始显示文本 */
  rawText: string
  /** 转换后显示文本（失败则为 null） */
  convertedText: string | null
  /** 是否转换失败 */
  failed: boolean
}

const TS_EPOCH_MIN_SEC = 1e9
const TS_EPOCH_MAX_SEC = 4102444800
const TS_EPOCH_MAX_MS = 4102444800000

/** 图片元数据列表值（WPS 图片单元格解析产物）→ 友好展示文本；非该形态返回 null */
function imageListText(raw: unknown): string | null {
  let items: unknown[] | null = null
  if (Array.isArray(raw)) items = raw
  else if (typeof raw === 'string' && raw.trim().startsWith('[')) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) items = parsed
    } catch { /* 非 JSON 数组串，忽略 */ }
  }
  if (!items || items.length === 0) return null
  const names = items
    .map(it => (it && typeof it === 'object' ? String((it as Record<string, unknown>).filename ?? '') : String(it)))
    .filter(Boolean)
  if (names.length === 0) return null
  return `[图片] ${names.join(', ')}`
}

/** 判断原始值能否转为目标类型 —— 返回转换后的字符串或 null（失败） */
export function tryConvert(raw: unknown, targetType: string): CellTransform {
  const rawText = raw == null
    ? ''
    : targetType === 'image'
      ? (imageListText(raw) ?? String(raw))
      : String(raw)
  const stripped = rawText.trim()
  if (!stripped) return { rawText, convertedText: '', failed: false }

  switch (targetType) {
    case 'text':
    case 'longtext':
      return { rawText, convertedText: stripped, failed: false }

    case 'number': {
      const s = stripped.replace(/[,%¥$￥]/g, '').replace(/,/g, '')
      const n = Number(s)
      if (!Number.isFinite(n) || !Number.isInteger(n)) return { rawText, convertedText: null, failed: true }
      return { rawText, convertedText: String(n), failed: false }
    }
    case 'float': {
      const s = stripped.replace(/[¥$￥]/g, '').replace(/,/g, '')
      const n = Number(s)
      if (!Number.isFinite(n)) return { rawText, convertedText: null, failed: true }
      return { rawText, convertedText: String(n), failed: false }
    }
    case 'percentage': {
      const hasPct = stripped.endsWith('%')
      const s = hasPct ? stripped.slice(0, -1).trim() : stripped
      const n = Number(s.replace(/,/g, ''))
      if (!Number.isFinite(n)) return { rawText, convertedText: null, failed: true }
      return { rawText, convertedText: hasPct ? `${n}%` : `${n}%`, failed: false }
    }
    case 'boolean': {
      const low = stripped.toLowerCase()
      const truthy = new Set(['true', 'yes', 'y', '1', 'on', '是'])
      const falsy = new Set(['false', 'no', 'n', '0', 'off', '否'])
      if (truthy.has(low)) return { rawText, convertedText: 'true', failed: false }
      if (falsy.has(low)) return { rawText, convertedText: 'false', failed: false }
      // 数值 1/0 也接受
      if (stripped === '1') return { rawText, convertedText: 'true', failed: false }
      if (stripped === '0') return { rawText, convertedText: 'false', failed: false }
      return { rawText, convertedText: null, failed: true }
    }
    case 'date':
    case 'datetime': {
      // ISO / CN / 通用日期
      const d = tryParseDate(stripped)
      if (!d) return { rawText, convertedText: null, failed: true }
      if (targetType === 'date') return { rawText, convertedText: d.toISOString().slice(0, 10), failed: false }
      return { rawText, convertedText: d.toISOString().slice(0, 19).replace('T', ' '), failed: false }
    }
    case 'select':
    case 'multiselect':
      return { rawText, convertedText: stripped, failed: false }
    case 'timestamp': {
      // 与后端 TimestampFieldType.validate_value 对齐：秒级原样，毫秒级归一为秒显示
      const n = Number(stripped.replace(/,/g, ''))
      if (!Number.isInteger(n)) return { rawText, convertedText: null, failed: true }
      if (n >= TS_EPOCH_MIN_SEC && n <= TS_EPOCH_MAX_SEC) {
        return { rawText, convertedText: String(n), failed: false }
      }
      if (n > TS_EPOCH_MAX_SEC && n <= TS_EPOCH_MAX_MS) {
        return { rawText, convertedText: String(Math.floor(n / 1000)), failed: false }
      }
      return { rawText, convertedText: null, failed: true }
    }
    case 'email':
      return { rawText, convertedText: stripped, failed: false }
    case 'url':
      return { rawText, convertedText: stripped, failed: false }
    case 'phone':
      return { rawText, convertedText: stripped, failed: false }
    case 'image':
      // WPS 图片单元格解析产物：rawText 已是「[图片] 文件名」友好文本
      return { rawText, convertedText: stripped, failed: false }
    default:
      return { rawText, convertedText: stripped, failed: false }
  }
}

/** 尝试解析日期字符串 —— 覆盖常见格式. */
function tryParseDate(s: string): Date | null {
  // ISO 8601
  let d = new Date(s)
  if (!Number.isNaN(d.getTime())) return d
  // 中文日期 2024/01/05 或 2024-01-05 或 2024.01.05
  const cn1 = s.match(/^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$/)
  if (cn1) {
    d = new Date(Number(cn1[1]), Number(cn1[2]) - 1, Number(cn1[3]))
    if (!Number.isNaN(d.getTime())) return d
  }
  // 带时间 2024-01-05 12:34:56
  const cn2 = s.match(/^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})[\sT]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/)
  if (cn2) {
    d = new Date(Number(cn2[1]), Number(cn2[2]) - 1, Number(cn2[3]), Number(cn2[4]), Number(cn2[5]), Number(cn2[6] || 0))
    if (!Number.isNaN(d.getTime())) return d
  }
  return null
}

/** 从多批 sample_rows 中提取原始唯一值 —— 作为 select 默认 options. */
export function collectUniqueValues(rows: Array<Record<string, unknown>>, colName: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const r of rows) {
    const v = r[colName]
    if (v == null) continue
    const s = String(v).trim()
    if (!s) continue
    if (!seen.has(s)) {
      seen.add(s)
      out.push(s)
    }
    if (out.length >= 200) break
  }
  return out
}

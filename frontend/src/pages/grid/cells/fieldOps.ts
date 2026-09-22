import type { Field } from '@/api'

/** 新增行草稿预填值：default_value 优先，其次 date/datetime 的 auto_fill 规则，否则 undefined.
 *
 * text 字段启用自动编号（config.default_mode=auto_increment）时返回 undefined：
 * 编号由后端建行时按库内已有数据推算（客户端猜测与库内 max 可能不一致），不预填.
 *
 * 供 GridPage 行内新增 和 RowDetailDrawer 抽屉新建行共用 —— 两处必须保持相同的预填语义.
 */
export function defaultValueForNewRow(f: Field): unknown {
  if (f.field_type === 'text' && (f.config?.default_mode as string) === 'auto_increment') {
    return undefined
  }
  if (f.default_value !== null && f.default_value !== undefined && f.default_value !== '') {
    return f.default_value
  }
  const autoFill = (f.config?.auto_fill as string) ?? ''
  if (f.field_type === 'date' && (autoFill === 'on_create' || autoFill === 'on_update')) {
    // 延迟 import：fieldOps.ts 是纯工具模块，不预先加载 dayjs
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const dayjs = require('dayjs')
    return dayjs().format('YYYY-MM-DD')
  }
  if (f.field_type === 'datetime' && (autoFill === 'on_create' || autoFill === 'on_update')) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const dayjs = require('dayjs')
    return dayjs().format('YYYY-MM-DD HH:mm:ss')
  }
  return undefined
}

/** 字段类型 → 可用筛选操作符映射 + 别名解析.
 *
 * 被 ColumnFilterDropdown、ViewConfigDialog 和 GridPage 的列构建器共用.
 * GridPage.tsx 原先重复定义了两套（FIELD_OPS / FIELD_OPS_BY_TYPE），
 * 本文件合并为一套统一真相源.
 */

export interface FieldOp {
  op: string
  label: string
  /** 是否不需要输入值（is_empty / is_not_empty 等） */
  needValue?: boolean
  /** 值编辑器类型 — 决定 UI 渲染哪种输入控件 */
  valueKind?: 'text' | 'number' | 'select' | 'date' | 'boolean'
}

// ── 后端真实 field_type name → 前端操作符组映射 ───────────────
// key 必须匹配后端 FieldType.name 的真实值
const FIELD_OPS_BY_TYPE: Record<string, FieldOp[]> = {
  text: [
    { op: 'contains', label: '包含', valueKind: 'text' },
    { op: 'starts_with', label: '开头为', valueKind: 'text' },
    { op: 'ends_with', label: '结尾为', valueKind: 'text' },
    { op: '=', label: '等于', valueKind: 'text' },
    { op: '!=', label: '不等于', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  longtext: [
    { op: 'contains', label: '包含', valueKind: 'text' },
    { op: 'starts_with', label: '开头为', valueKind: 'text' },
    { op: 'ends_with', label: '结尾为', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  number: [
    { op: '=', label: '等于', valueKind: 'number' },
    { op: '!=', label: '不等于', valueKind: 'number' },
    { op: '>', label: '大于', valueKind: 'number' },
    { op: '>=', label: '大于等于', valueKind: 'number' },
    { op: '<', label: '小于', valueKind: 'number' },
    { op: '<=', label: '小于等于', valueKind: 'number' },
    { op: 'in', label: '在列表中（逗号分隔）', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  float: [
    { op: '=', label: '等于', valueKind: 'number' },
    { op: '!=', label: '不等于', valueKind: 'number' },
    { op: '>', label: '大于', valueKind: 'number' },
    { op: '>=', label: '大于等于', valueKind: 'number' },
    { op: '<', label: '小于', valueKind: 'number' },
    { op: '<=', label: '小于等于', valueKind: 'number' },
    { op: 'in', label: '在列表中（逗号分隔）', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  percentage: [
    { op: '=', label: '等于', valueKind: 'number' },
    { op: '!=', label: '不等于', valueKind: 'number' },
    { op: '>', label: '大于', valueKind: 'number' },
    { op: '>=', label: '大于等于', valueKind: 'number' },
    { op: '<', label: '小于', valueKind: 'number' },
    { op: '<=', label: '小于等于', valueKind: 'number' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  timestamp: [
    { op: '=', label: '等于', valueKind: 'number' },
    { op: '!=', label: '不等于', valueKind: 'number' },
    { op: '>', label: '大于', valueKind: 'number' },
    { op: '>=', label: '大于等于', valueKind: 'number' },
    { op: '<', label: '小于', valueKind: 'number' },
    { op: '<=', label: '小于等于', valueKind: 'number' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  select: [
    { op: '=', label: '等于', valueKind: 'select' },
    { op: '!=', label: '不等于', valueKind: 'select' },
    { op: 'in', label: '属于', valueKind: 'select' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  multiselect: [
    { op: 'contains', label: '包含值', valueKind: 'select' },
    { op: 'in', label: '属于任一', valueKind: 'select' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  date: [
    { op: '=', label: '等于', valueKind: 'date' },
    { op: '>', label: '晚于', valueKind: 'date' },
    { op: '>=', label: '晚于或等于', valueKind: 'date' },
    { op: '<', label: '早于', valueKind: 'date' },
    { op: '<=', label: '早于或等于', valueKind: 'date' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  datetime: [
    { op: '=', label: '等于', valueKind: 'date' },
    { op: '>', label: '晚于', valueKind: 'date' },
    { op: '>=', label: '晚于或等于', valueKind: 'date' },
    { op: '<', label: '早于', valueKind: 'date' },
    { op: '<=', label: '早于或等于', valueKind: 'date' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  boolean: [
    { op: '=', label: '等于', valueKind: 'boolean' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  email: [
    { op: 'contains', label: '包含', valueKind: 'text' },
    { op: '=', label: '等于', valueKind: 'text' },
    { op: '!=', label: '不等于', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  phone: [
    { op: 'contains', label: '包含', valueKind: 'text' },
    { op: '=', label: '等于', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  url: [
    { op: 'contains', label: '包含', valueKind: 'text' },
    { op: 'starts_with', label: '开头为', valueKind: 'text' },
    { op: 'is_empty', label: '为空', needValue: true },
    { op: 'is_not_empty', label: '不为空', needValue: true },
  ],
  attachment: [
    { op: 'is_empty', label: '无附件', needValue: true },
    { op: 'is_not_empty', label: '有附件', needValue: true },
  ],
  link: [
    { op: 'is_empty', label: '未关联', needValue: true },
    { op: 'is_not_empty', label: '已关联', needValue: true },
    { op: 'has_any', label: '包含任一目标行（逗号分隔 id）', valueKind: 'text' },
    { op: 'has_all', label: '包含全部目标行（逗号分隔 id）', valueKind: 'text' },
  ],
}

// ── 旧 field_type name → 新 field_type name 的别名映射 ───────────────
// 兼容历史数据 / 过渡期间前后端不同步
export const FIELD_TYPE_ALIASES: Record<string, string> = {
  long_text: 'longtext',
  decimal: 'float',
  multi_select: 'multiselect',
  rich_text: 'longtext',
  link_to_table: 'link',
}

/** 根据 field_type（先解析别名）返回可用操作符列表；兜底返回 text 操作符组 */
export function getOpsForField(fieldType: string): FieldOp[] {
  const resolved = FIELD_TYPE_ALIASES[fieldType] ?? fieldType
  return FIELD_OPS_BY_TYPE[resolved] || FIELD_OPS_BY_TYPE.text
}

// ── select / multiselect 字段 options 提取 ──────────────

/** 从 field.config 里提取 select options，统一转为 [{value, label}] 格式.
 *
 * 兼容两种历史格式：
 * - 后端 transfer.py 旧输出：list[str] — ["active", "done"]
 * - 后端 SelectFieldConfig 新输出：list[dict] — [{label: "active", value: "active", color: "blue"}]
 */
export interface SelectOption {
  value: string
  label: string
  color?: string
}

export function extractSelectOptions(config: unknown): SelectOption[] {
  if (!config || typeof config !== 'object') return []
  const c = config as { options?: unknown[] }
  const opts = c.options
  if (!Array.isArray(opts) || opts.length === 0) return []
  if (typeof opts[0] === 'string') {
    return (opts as string[]).map((v) => ({ value: v, label: v }))
  }
  return (opts as Array<Record<string, unknown>>).map((o) => ({
    value: String(o.value ?? o.name ?? ''),
    label: String(o.label ?? o.value ?? o.name ?? ''),
    ...(o.color ? { color: String(o.color) } : {}),
  })).filter((o) => o.value || o.label)
}

/** 视图专属配置字段 schema — Kanban / Calendar / Gallery 共用的真相源.
 *
 * ViewConfigDialog（编辑已存视图的视图设置 Tab）和 CreateEditViewForm（创建/编辑视图时的配置表单）
 * 都应该从这里拿字段定义，确保 label / 类型约束 / 默认值三处一致。
 */

import type { Field } from '@/api'
import { FIELD_TYPE_ALIASES } from './fieldOps'

// ── schema 类型 ──────────────────────────────────────────

/** 单个视图专属 option 字段的 schema */
export interface ViewOptionSchema {
  /** JSON key — 对应 view_options 对象里的字段名 */
  key: string
  /** 显示 label */
  label: string
  /** 可选的 tooltip 说明 */
  tooltip?: string
  /** 是否必填（影响 CreateEditViewForm 的 Form.Item required prop） */
  required?: boolean
  /** 值编辑控件类型 */
  kind:
    | 'field_select'       // 单字段下拉
    | 'field_multi_select'  // 多字段下拉
    | 'enum_select'         // 固定 enum 值下拉
    | 'direction'           // 升/降方向
    | 'switch'              // 开/关
    | 'number_enum'         // 数值枚举下拉
  /** 允许的后端 field_type 原始名 + 历史别名集合（FieldType.name 或别名都可匹配）.
   *  数组顺序即自动推断时的优先级（先排先试）。 */
  fieldTypes?: string[]
  /** 自动推断时是否同时把主键字段作为候选（title_field / group_field 等常见） */
  includePrimary?: boolean
  /** 自动推断失败后的字面量 fallback 值（如 'id'） */
  literalFallback?: string
  /** 枚举值（kind='enum_select'/'direction'/'number_enum' 时必填） */
  enumOptions?: Array<{ value: string | number | boolean; label: string }>
  /** 默认值（未配置时回退） */
  defaultValue?: unknown
}

// ── 各视图的 option schema 列表 ─────────────────────────

/** Kanban 看板视图的专属配置字段（共 11 项） */
export const KANBAN_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'group_field', label: '分组字段', tooltip: '按哪个字段分组显示为看板列',
    kind: 'field_select', fieldTypes: ['select', 'multiselect', 'boolean', 'link'], required: true,
  },
  {
    key: 'title_field', label: '卡片标题字段', tooltip: '留空使用主键字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'], includePrimary: true, literalFallback: 'id',
  },
  {
    key: 'progress_field', label: '进度百分比字段', tooltip: '0-100 的数值字段，显示进度条',
    kind: 'field_select', fieldTypes: ['number', 'float', 'percentage', 'timestamp'],
  },
  {
    key: 'due_date_field', label: '截止日期字段', tooltip: '配置后自动显示逾期/临近提醒',
    kind: 'field_select', fieldTypes: ['date', 'datetime'],
  },
  {
    key: 'priority_field', label: '优先级字段', tooltip: 'Select 字段，不同值显示不同颜色徽章',
    kind: 'field_select', fieldTypes: ['select', 'multiselect'],
  },
  {
    key: 'assignee_field', label: '负责人字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'],
  },
  {
    key: 'card_sort_field', label: '卡片排序字段', tooltip: '每列卡片按此字段排序；留空则按 API 返回顺序 + 紧急置顶',
    kind: 'field_select', fieldTypes: ['__all__'],
  },
  {
    key: 'card_sort_direction', label: '卡片排序方向', tooltip: '配合卡片排序字段使用',
    kind: 'direction', defaultValue: 'desc',
    enumOptions: [
      { value: 'asc', label: '升序 ↑' },
      { value: 'desc', label: '降序 ↓' },
    ],
  },
  {
    key: 'pin_urgent', label: '逾期/紧急卡片置顶', tooltip: '有截止日期时，逾期和临近截止的卡片始终排在列顶',
    kind: 'switch', defaultValue: true,
  },
  {
    key: 'card_fields', label: '卡片额外字段', tooltip: '在卡片底部以标签形式展示',
    kind: 'field_multi_select', fieldTypes: ['__all__'],
  },
  {
    key: 'urgent_threshold_days', label: '紧急阈值（天）', tooltip: '截止日期前多少天标记为紧急',
    kind: 'number_enum', defaultValue: 3,
    enumOptions: [
      { value: 1, label: '1 天' }, { value: 3, label: '3 天' },
      { value: 5, label: '5 天' }, { value: 7, label: '7 天' },
    ],
  },
]

/** Calendar 日历视图的专属配置字段（共 4 项） */
export const CALENDAR_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'start_field', label: '日期字段', tooltip: '事件的日期',
    kind: 'field_select', fieldTypes: ['date', 'datetime'], required: true,
  },
  {
    key: 'title_field', label: '事件标题字段', tooltip: '日历格中显示的事件文字；留空则自动选第一个文本字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext', 'is_primary'],
  },
  {
    key: 'group_field', label: '分组/颜色字段', tooltip: 'Select 字段，不同值渲染不同颜色侧边条',
    kind: 'field_select', fieldTypes: ['select', 'multiselect'],
  },
  {
    key: 'calendar_mode', label: '默认打开的日历层级',
    kind: 'enum_select', defaultValue: 'month',
    enumOptions: [
      { value: 'year', label: '年视图（12 月概览）' },
      { value: 'month', label: '月视图（标准日历）' },
      { value: 'week', label: '周视图（7 天横向）' },
    ],
  },
]

/** Gallery 画廊视图的专属配置字段（共 5 项） */
export const GALLERY_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'title_field', label: '标题字段', tooltip: '留空则自动选第一个文本字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'], includePrimary: true, literalFallback: 'id',
  },
  {
    key: 'subtitle_field', label: '副标题字段', tooltip: '卡片标题下方的补充文字',
    kind: 'field_select', fieldTypes: ['__all__'],
  },
  {
    key: 'tag_field', label: '标签字段', tooltip: '显示为卡片右上角徽章',
    kind: 'field_select', fieldTypes: ['select', 'multiselect', 'boolean'],
  },
  {
    key: 'meta_fields', label: '附加信息字段', tooltip: '显示在卡片底部的小标签（可多选）',
    kind: 'field_multi_select', fieldTypes: ['__all__'],
  },
  {
    key: 'image_field', label: '图片/附件字段', tooltip: '留空则自动选第一个附件字段',
    kind: 'field_select', fieldTypes: ['attachment', 'image'],
  },
]

/** 按 view_type 名返回 option schema 列表 */
export function getOptionSchema(viewType: string): ViewOptionSchema[] {
  switch (viewType) {
    case 'kanban': return KANBAN_OPTIONS
    case 'calendar': return CALENDAR_OPTIONS
    case 'gallery': return GALLERY_OPTIONS
    default: return []
  }
}

// ── 从 schema 生成 options 下拉列表的辅助 ──────────────

/** 判断一个 Field 是否匹配 schema.fieldTypes（支持 __all__ 通配符和别名） */
export function _fieldMatchesSchema(field: Field, fieldTypes: string[] | undefined): boolean {
  if (!fieldTypes) return true
  if (fieldTypes.includes('__all__')) return !field.hidden
  const ft = field.field_type
  const alias = FIELD_TYPE_ALIASES[ft] ?? ft
  if (field.is_primary && fieldTypes.includes('is_primary')) return true
  return fieldTypes.includes(ft) || fieldTypes.includes(alias)
}

/** 根据 schema.fieldTypes 从 fields 过滤出匹配的 options */
export function resolveFieldOptions(fields: Field[], schema: ViewOptionSchema): Array<{ value: string; label: string }> {
  return fields
    .filter(f => _fieldMatchesSchema(f, schema.fieldTypes))
    .map(f => ({ value: f.name, label: `${f.name} (${f.field_type})` }))
}

/** 按 schema 从原始 opts 对象解析出完整配置 — 自动应用 defaultValue 回退.
 *
 * KanbanView / CalendarView / GalleryView 在组件顶层调用一次，
 * 得到统一默认值后的配置对象，再传给内部子组件（KanbanCard / sortKanbanCards 等），
 * 避免每个子组件各自写一遍 `opts.xxx ?? default` 回退逻辑。
 */
export function resolveOpts(
  rawOpts: Record<string, unknown> | undefined | null,
  schema: ViewOptionSchema[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const opt of schema) {
    const raw = rawOpts?.[opt.key]
    // switch 的 false 是有效值，不能回退到 defaultValue；undefined 才回退
    if (raw === undefined || raw === null) {
      if (opt.defaultValue !== undefined) out[opt.key] = opt.defaultValue
    } else {
      out[opt.key] = raw
    }
  }
  // 不在 schema 里的额外字段原样保留（向后兼容）
  if (rawOpts) {
    for (const [k, v] of Object.entries(rawOpts)) {
      if (!(k in out)) out[k] = v
    }
  }
  return out
}

// ── 自动推断字段名（消费方 fallback） ──────────────────

/** 从 schema 里找指定 key 的 option 定义 */
export function findOptionSchema(viewType: string, key: string): ViewOptionSchema | undefined {
  return getOptionSchema(viewType).find(o => o.key === key)
}

/** 按 schema 的 fieldTypes 优先级推断默认字段名.
 *
 * 按 fieldTypes 数组顺序依次尝试每个 type，取第一个匹配的字段；
 * 若 includePrimary 为 true 且没匹配到，再用主键字段；
 * 还没匹配到就返回 literalFallback（如 'id'）或 undefined。
 */
export function resolveAutoField(
  fields: Field[],
  schema: ViewOptionSchema | undefined,
): string | undefined {
  if (!schema) return undefined

  const matchType = (type: string): Field | undefined => {
    if (type === '__all__') return fields.find(f => !f.hidden)
    if (type === 'is_primary') return fields.find(f => f.is_primary)
    const alias = FIELD_TYPE_ALIASES[type] ?? type
    return fields.find(f => f.field_type === type || f.field_type === alias)
  }

  if (schema.fieldTypes) {
    for (const ft of schema.fieldTypes) {
      const f = matchType(ft)
      if (f) return f.name
    }
  }

  if (schema.includePrimary) {
    const primary = fields.find(f => f.is_primary)
    if (primary) return primary.name
  }

  return schema.literalFallback as string | undefined
}

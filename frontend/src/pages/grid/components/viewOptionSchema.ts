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
  /** 表单分区名（创建/编辑视图对话框的分区卡片与折叠）; 缺省归入「其他」 */
  group?: string
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
  | 'done_flag'           // 完成标志：字段下拉 + 按字段类型动态切换的匹配值控件（存 done_field + done_value 两键）
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

/** Kanban 看板视图的专属配置字段（共 14 项） */
export const KANBAN_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'group_field', label: '分组字段', group: '分组与标题', tooltip: '按哪个字段分组显示为看板列',
    kind: 'field_select', fieldTypes: ['select', 'multiselect', 'boolean', 'link'], required: true,
  },
  {
    key: 'title_field', label: '卡片标题字段', group: '分组与标题', tooltip: '留空使用主键字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'], includePrimary: true, literalFallback: 'id',
  },
  {
    key: 'progress_field', label: '进度百分比字段', group: '字段映射', tooltip: '0-100 的数值字段，显示进度条',
    kind: 'field_select', fieldTypes: ['number', 'float', 'percentage', 'timestamp'],
  },
  {
    key: 'due_date_field', label: '截止日期字段', group: '字段映射', tooltip: '配置后自动显示逾期/临近提醒',
    kind: 'field_select', fieldTypes: ['date', 'datetime'],
  },
  {
    key: 'priority_field', label: '优先级字段', group: '字段映射', tooltip: 'Select 字段，不同值显示不同颜色徽章',
    kind: 'field_select', fieldTypes: ['select', 'multiselect'],
  },
  {
    key: 'assignee_field', label: '负责人字段', group: '字段映射',
    kind: 'field_select', fieldTypes: ['text', 'longtext'],
  },
  {
    key: 'card_sort_field', label: '卡片排序字段', group: '排序与提醒', tooltip: '每列卡片按此字段排序；留空则按 API 返回顺序 + 紧急置顶',
    kind: 'field_select', fieldTypes: ['__all__'],
  },
  {
    key: 'card_sort_direction', label: '卡片排序方向', group: '排序与提醒', tooltip: '配合卡片排序字段使用',
    kind: 'direction', defaultValue: 'desc',
    enumOptions: [
      { value: 'asc', label: '升序 ↑' },
      { value: 'desc', label: '降序 ↓' },
    ],
  },
  {
    key: 'pin_urgent', label: '逾期/紧急卡片置顶', group: '排序与提醒', tooltip: '有截止日期时，逾期和临近截止的卡片始终排在列顶',
    kind: 'switch', defaultValue: true,
  },
  {
    key: 'card_fields', label: '卡片额外字段', group: '分组与标题', tooltip: '在卡片底部以标签形式展示',
    kind: 'field_multi_select', fieldTypes: ['__all__'],
  },
  {
    key: 'urgent_threshold_days', label: '紧急阈值（天）', group: '排序与提醒', tooltip: '截止日期前多少天标记为紧急',
    kind: 'number_enum', defaultValue: 3,
    enumOptions: [
      { value: 1, label: '1 天' }, { value: 3, label: '3 天' },
      { value: 5, label: '5 天' }, { value: 7, label: '7 天' },
    ],
  },
  {
    key: 'done_field', label: '完成标志', group: '完成状态', tooltip: '选择字段并指定匹配值，满足条件的卡片以完成状态显示（绿底灰字、隐藏倒计时提醒）',
    kind: 'done_flag', fieldTypes: ['boolean', 'select', 'multiselect', 'text', 'longtext'],
  },
  {
    key: 'done_bg_color', label: '完成卡片背景色', group: '完成状态', tooltip: '完成状态卡片的背景颜色',
    kind: 'enum_select', defaultValue: 'auto',
    enumOptions: [
      { value: 'auto', label: '跟随主题（默认绿）' },
      { value: '#f6ffed', label: '绿色' },
      { value: '#e6f4ff', label: '蓝色' },
      { value: '#f9f0ff', label: '紫色' },
      { value: '#fff7e6', label: '橙色' },
      { value: '#f5f5f5', label: '灰色' },
    ],
  },
  {
    key: 'done_text_color', label: '完成卡片文字颜色', group: '完成状态', tooltip: '完成状态卡片标题的文字颜色',
    kind: 'enum_select', defaultValue: 'auto',
    enumOptions: [
      { value: 'auto', label: '跟随主题（默认灰）' },
      { value: '#8c8c8c', label: '灰色' },
      { value: '#595959', label: '深灰' },
      { value: '#389e0d', label: '绿色' },
      { value: '#1677ff', label: '蓝色' },
      { value: '#cf1322', label: '红色' },
    ],
  },
]

/** Calendar 日历视图的专属配置字段（共 4 项） */
export const CALENDAR_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'start_field', label: '日期字段', group: '日历配置', tooltip: '事件的日期',
    kind: 'field_select', fieldTypes: ['date', 'datetime'], required: true,
  },
  {
    key: 'title_field', label: '事件标题字段', group: '日历配置', tooltip: '日历格中显示的事件文字；留空则自动选第一个文本字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext', 'is_primary'],
  },
  {
    key: 'group_field', label: '分组/颜色字段', group: '日历配置', tooltip: 'Select 字段，不同值渲染不同颜色侧边条',
    kind: 'field_select', fieldTypes: ['select', 'multiselect'],
  },
  {
    key: 'calendar_mode', label: '默认打开的日历层级', group: '日历配置',
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
    key: 'title_field', label: '标题字段', group: '标题与图片', tooltip: '留空则自动选第一个文本字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'], includePrimary: true, literalFallback: 'id',
  },
  {
    key: 'subtitle_field', label: '副标题字段', group: '标题与图片', tooltip: '卡片标题下方的补充文字',
    kind: 'field_select', fieldTypes: ['__all__'],
  },
  {
    key: 'tag_field', label: '标签字段', group: '标签与信息', tooltip: '显示为卡片右上角徽章',
    kind: 'field_select', fieldTypes: ['select', 'multiselect', 'boolean'],
  },
  {
    key: 'meta_fields', label: '附加信息字段', group: '标签与信息', tooltip: '显示在卡片底部的小标签（可多选）',
    kind: 'field_multi_select', fieldTypes: ['__all__'],
  },
  {
    key: 'image_field', label: '图片/附件字段', group: '标题与图片', tooltip: '留空则自动选第一个附件字段',
    kind: 'field_select', fieldTypes: ['attachment', 'image'],
  },
]

/** Gantt 甘特图视图的专属配置字段（共 9 项） */
export const GANTT_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'start_date_field', label: '开始日期字段', group: '日期字段', tooltip: '任务/项目的开始日期',
    kind: 'field_select', fieldTypes: ['date', 'datetime'], required: true,
  },
  {
    key: 'end_date_field', label: '结束日期字段', group: '日期字段', tooltip: '任务/项目的截止日期或计划交付日期',
    kind: 'field_select', fieldTypes: ['date', 'datetime'], required: true,
  },
  {
    key: 'actual_end_field', label: '实际完成日期字段', group: '日期字段', tooltip: '可选：用于显示实际完成时间与计划的对比',
    kind: 'field_select', fieldTypes: ['date', 'datetime'],
  },
  {
    key: 'title_field', label: '任务名称字段', group: '显示字段', tooltip: '甘特条左侧显示的任务名称；留空自动选第一个文本字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'], includePrimary: true, literalFallback: 'id',
  },
  {
    key: 'group_field', label: '分组/着色字段', group: '显示字段', tooltip: 'Select 字段，不同分组渲染不同颜色的甘特条',
    kind: 'field_select', fieldTypes: ['select', 'multiselect'],
  },
  {
    key: 'progress_field', label: '进度百分比字段', group: '显示字段', tooltip: '0-100 的数值字段，在甘特条上显示进度填充',
    kind: 'field_select', fieldTypes: ['number', 'float', 'percentage'],
  },
  {
    key: 'assignee_field', label: '负责人字段', group: '显示字段', tooltip: '在甘特条下方显示负责人名称',
    kind: 'field_select', fieldTypes: ['text', 'longtext'],
  },
  {
    key: 'time_scale', label: '时间刻度', group: '时间轴', tooltip: '默认显示的时间粒度',
    kind: 'enum_select', defaultValue: 'month',
    enumOptions: [
      { value: 'day', label: '天（精细）' },
      { value: 'week', label: '周（中等）' },
      { value: 'month', label: '月（标准）' },
      { value: 'quarter', label: '季度（粗粒度）' },
    ],
  },
  {
    key: 'show_today_line', label: '显示今日标线', group: '时间轴', tooltip: '在甘特图中用红色竖线标记今天的位置',
    kind: 'switch', defaultValue: true,
  },
]

/** WBS 工作分解结构视图的专属配置字段（共 9 项） */
export const WBS_OPTIONS: ViewOptionSchema[] = [
  {
    key: 'parent_field', label: '父任务字段', group: '结构字段', tooltip: '哪个字段存储父任务关联（link 指向同表自身，或文本/数字存父 ID）',
    kind: 'field_select', fieldTypes: ['link', 'text', 'number', 'decimal', 'is_primary'], required: true,
  },
  {
    key: 'title_field', label: '任务名称字段', group: '结构字段', tooltip: '树节点显示的主标题；留空自动选第一个文本字段',
    kind: 'field_select', fieldTypes: ['text', 'longtext'], includePrimary: true, literalFallback: 'id',
  },
  {
    key: 'progress_field', label: '进度百分比字段', group: '显示字段', tooltip: '0-100 的数值字段；父节点自动按子节点平均计算',
    kind: 'field_select', fieldTypes: ['number', 'float', 'percentage'],
  },
  {
    key: 'status_field', label: '状态字段', group: '显示字段', tooltip: 'Select 字段，显示为状态徽章',
    kind: 'field_select', fieldTypes: ['select', 'multiselect'],
  },
  {
    key: 'assignee_field', label: '负责人字段', group: '显示字段', tooltip: '在节点右侧显示负责人名称',
    kind: 'field_select', fieldTypes: ['text', 'longtext'],
  },
  {
    key: 'start_date_field', label: '开始日期字段', group: '显示字段', tooltip: '可选：在节点上显示时间跨度',
    kind: 'field_select', fieldTypes: ['date', 'datetime'],
  },
  {
    key: 'end_date_field', label: '结束日期字段', group: '显示字段', tooltip: '可选：与开始日期配合显示区间',
    kind: 'field_select', fieldTypes: ['date', 'datetime'],
  },
  {
    key: 'show_numbering', label: '显示层级编号', group: '操作', tooltip: '在任务名前显示 1 / 1.1 / 1.1.1 样式的编号',
    kind: 'switch', defaultValue: true,
  },
  {
    key: 'expand_all', label: '默认全部展开', group: '操作', tooltip: '首次加载时是否展开所有层级；关闭则只展开第一层',
    kind: 'switch', defaultValue: false,
  },
]

/** 按 view_type 名返回 option schema 列表 */
export function getOptionSchema(viewType: string): ViewOptionSchema[] {
  switch (viewType) {
    case 'kanban': return KANBAN_OPTIONS
    case 'calendar': return CALENDAR_OPTIONS
    case 'gallery': return GALLERY_OPTIONS
    case 'gantt': return GANTT_OPTIONS
    case 'wbs': return WBS_OPTIONS
    default: return []
  }
}

// ── 表单分区（创建/编辑视图对话框） ─────────────────────

/** 一个表单分区：分区标题 + 该分区下的 option（保持 schema 原顺序） */
export interface ViewOptionSection {
  /** 分区标题（取自 option.group） */
  label: string
  /** 分区内的 option 列表 */
  items: ViewOptionSchema[]
}

/** 按 option.group 保序切分 schema.
 *
 * 分区顺序 = 分区名首次出现的顺序；同分区内保持 schema 原顺序；
 * 未标注 group 的 option 统一归入「其他」（因此排在最后，除非显式声明过该名）。
 */
export function groupOptionSchema(schema: ViewOptionSchema[]): ViewOptionSection[] {
  const sections: ViewOptionSection[] = []
  for (const opt of schema) {
    const label = opt.group ?? '其他'
    let section = sections.find((s) => s.label === label)
    if (!section) {
      section = { label, items: [] }
      sections.push(section)
    }
    section.items.push(opt)
  }
  return sections
}

/** option 在创建/编辑视图表单两列网格中占的列数.
 *
 * 短控件（开关 / 方向 / 枚举下拉）占 1 列；字段下拉与复合控件占 2 列（整行），
 * 因为它们的候选文本较长、两列并排会被压扁。
 */
export function optionColSpan(kind: ViewOptionSchema['kind']): 1 | 2 {
  if (kind === 'switch' || kind === 'direction' || kind === 'enum_select' || kind === 'number_enum') {
    return 1
  }
  return 2
}

/** 创建/编辑视图对话框中默认收起的分区（次要配置，收起以压缩首屏高度） */
export const COLLAPSED_BY_DEFAULT_GROUPS: ReadonlySet<string> = new Set([
  '完成状态',
  '时间轴',
  '操作',
])

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

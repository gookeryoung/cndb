/** 字段类型元数据单一真相源 —— 中文标签 / 类别 / antd 预设色.
 *
 * 全项目所有展示字段类型标签的位置（表设置字段管理、导入数据预览下拉与图例、
 * 报表字段面板、API 导入列头等）一律从本模块取值，保证同一类型在任意界面
 * 显示同一中文标签与同一颜色.
 *
 * 配色为 antd 预设色名（直接传给 <Tag color={...}>），同类别同色系、
 * 异类别可区分；历史别名与系统类型统一走 default 兜底色.
 */

import type { FieldType } from '@/api/types'

export interface FieldTypeMeta {
    /** 中文标签（如「单行文本」） */
    label: string
    /** 中文类别（如「基础」） */
    category: string
    /** antd 预设色名 */
    color: string
}

/** 16 个主字段类型 + 历史别名/系统类型的元数据表 */
export const FIELD_TYPE_META: Record<string, FieldTypeMeta> = {
    // ── 主类型（与 api/types.ts FieldType 联合对应）──
    text: { label: '单行文本', category: '基础', color: 'blue' },
    longtext: { label: '多行文本', category: '基础', color: 'cyan' },
    boolean: { label: '是/否', category: '基础', color: 'purple' },
    number: { label: '整数', category: '数字', color: 'green' },
    float: { label: '小数', category: '数字', color: 'green' },
    percentage: { label: '百分比', category: '数字', color: 'lime' },
    date: { label: '日期', category: '日期', color: 'orange' },
    datetime: { label: '日期时间', category: '日期', color: 'orange' },
    timestamp: { label: '时间戳', category: '日期', color: 'orange' },
    select: { label: '单选', category: '选择', color: 'gold' },
    multiselect: { label: '多选', category: '选择', color: 'gold' },
    email: { label: '邮箱', category: '高级', color: 'geekblue' },
    url: { label: '链接', category: '高级', color: 'geekblue' },
    phone: { label: '电话', category: '高级', color: 'geekblue' },
    link: { label: '关联', category: '关联', color: 'magenta' },
    attachment: { label: '附件', category: '高级', color: 'volcano' },
    // ── 历史别名（后端自动归一化，展示兜底）──
    long_text: { label: '多行文本', category: '基础', color: 'cyan' },
    decimal: { label: '小数', category: '数字', color: 'green' },
    multi_select: { label: '多选', category: '选择', color: 'gold' },
    json: { label: 'JSON', category: '高级', color: 'default' },
    // ── 系统类型（展示兜底）──
    formula: { label: '公式', category: '系统', color: 'default' },
    auto_id: { label: '自动编号', category: '系统', color: 'default' },
    created_time: { label: '创建时间', category: '系统', color: 'default' },
    updated_time: { label: '更新时间', category: '系统', color: 'default' },
    created_by: { label: '创建人', category: '系统', color: 'default' },
    updated_by: { label: '更新人', category: '系统', color: 'default' },
}

/** 取字段类型的中文标签；未知类型返回原始值（与既有 `?? type` 兜底语义一致） */
export function getFieldTypeLabel(type: string): string {
    return FIELD_TYPE_META[type]?.label ?? type
}

/** 取字段类型的 antd 预设色名；未知类型返回 'default'（与既有 `?? 'default'` 兜底语义一致） */
export function getFieldTypeColor(type: string): string {
    return FIELD_TYPE_META[type]?.color ?? 'default'
}

/** 新建/编辑字段下拉的完整类型选项（16 主类型，含类别） */
export const FIELD_TYPE_OPTIONS: Array<{ value: FieldType; label: string; category: string }> = [
    'text', 'longtext', 'boolean', 'number', 'float', 'percentage', 'date',
    'datetime', 'timestamp', 'select', 'multiselect', 'email', 'url', 'phone',
    'link', 'attachment',
].map((value) => {
    const meta = FIELD_TYPE_META[value]!
    return { value: value as FieldType, label: meta.label, category: meta.category }
})

/** 导入数据预览中允许切换的字段类型子集.
 *
 * 沿用原 FileImportPreview 的过滤语义：排除 link/attachment/formula 等
 * 不适合从原始数据推断的类型.
 * 包含 longtext/timestamp —— 后端推断层可产出这两种类型，
 * 下拉必须能显示其中文标签且允许用户手动切换回其它类型.
 */
export const PREVIEW_FIELD_TYPE_VALUES: readonly string[] = [
    'text', 'longtext', 'number', 'float', 'boolean', 'date', 'datetime',
    'timestamp', 'select', 'multiselect', 'email', 'url', 'phone', 'percentage',
]

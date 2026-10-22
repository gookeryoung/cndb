/** 卡片画廊纯逻辑层 — 配置解析、标签归一、元信息提取、列宽与批次常量（与 UI 解耦，可独立单测）.
 *
 * GalleryView 只负责渲染：默认值回退、字段自动推断、标签上限、空值剔除全部在这里完成，
 * 避免组件内部再写一遍 `opts.xxx ?? default` 逻辑（与 kanbanBoard.ts 同口径）。
 */

import type { Field, RowResponse } from '@/api'
import { extractSelectOptions } from '../cells/fieldOps'
import { formatFieldDisplayValue, formatMultiSelectValue, getSelectLabel } from '../cells/fieldValueFormat'

// ── 常量 ──────────────────────────────────────────────

/** 每批渲染的卡片数 —— 非 grid 视图最多拉 2000 行，全量挂载会明显卡顿 */
export const GALLERY_BATCH_SIZE = 48

/** card_size → 栅格最小列宽（px）；重复值用于测试断言 */
export const GALLERY_COLUMN_MIN_PX: Record<GalleryCardSize, number> = {
  small: 220,
  medium: 280,
  large: 360,
}

/** 单卡最多展示的标签数，超出以 `+N` 表示 */
export const GALLERY_MAX_TAGS = 6

/** 单卡最多展示的元信息项数 */
export const GALLERY_MAX_META = 4

// ── 类型 ──────────────────────────────────────────────

/** 卡片尺寸档位（决定栅格最小列宽） */
export type GalleryCardSize = 'small' | 'medium' | 'large'

/** 摘要截断行数档位 */
export type GallerySummaryLines = 2 | 3 | 4 | 6

/** 解析后的画廊配置（所有默认值已回退，GalleryView 直接用） */
export interface GalleryConfig {
  /** 卡片标题字段（title_field → 首个 text/longtext → 首字段 → 'id'） */
  titleField: string
  /** 摘要字段（summary_field → 首个 longtext，可空） */
  summaryField?: string
  /** 日期徽章字段（date_field → 首个 date/datetime，可空） */
  dateField?: string
  /** 彩色标签字段列表（非数组按空处理） */
  tagFields: string[]
  /** 底部元信息字段列表（非数组按空处理） */
  metaFields: string[]
  /** 卡片尺寸（非法值回退 medium） */
  cardSize: GalleryCardSize
  /** 摘要行数（非法值回退 3） */
  summaryLines: GallerySummaryLines
}

/** 单卡上的一个彩色标签 */
export interface GalleryTagItem {
  /** 标签显示文本（select/multiselect 取 option label，text 原样） */
  label: string
  /** 标签来源字段（取色用 field.config.options） */
  field: Field
}

/** 单卡上的一条元信息 */
export interface GalleryMetaItem {
  /** 来源字段 */
  field: Field
  /** 字段名（渲染为「字段名：值」） */
  label: string
  /** 格式化后的显示值（空值已在提取时剔除） */
  text: string
}

// ── 配置解析 ──────────────────────────────────────────

const CARD_SIZES: readonly GalleryCardSize[] = ['small', 'medium', 'large']
const SUMMARY_LINE_OPTIONS: readonly GallerySummaryLines[] = [2, 3, 4, 6]

/** 数组化列表型配置：仅接受数组，非数组（含字符串脏值）按空处理 */
function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((v): v is string => typeof v === 'string' && v.length > 0)
}

/** 按类型优先级取首个字段名（与 resolveAutoField 的非别名场景同口径） */
function firstFieldByType(fields: Field[], types: readonly string[]): string | undefined {
  for (const type of types) {
    const hit = fields.find((f) => f.field_type === type)
    if (hit) return hit.name
  }
  return undefined
}

/** 解析画廊配置（唯一入口）—— 应用默认值与自动推断，GalleryView 不得自行回退.
 *
 * 回退链：
 * - titleField：opts.title_field → 首个 text/longtext → 首字段 → 'id'
 * - summaryField：opts.summary_field → 首个 longtext（可空）
 * - dateField：opts.date_field → 首个 date/datetime（可空）
 * - tagFields / metaFields：仅数组（非数组按空处理，兼容历史脏值）
 * - cardSize：仅 small|medium|large，否则 medium
 * - summaryLines：仅 2|3|4|6，否则 3
 */
export function resolveGalleryConfig(
  fields: Field[],
  opts: Record<string, unknown> | null | undefined,
): GalleryConfig {
  const o = opts ?? {}
  const titleField =
    (typeof o.title_field === 'string' && o.title_field) ||
    firstFieldByType(fields, ['text', 'longtext']) ||
    fields[0]?.name ||
    'id'
  const summaryField =
    (typeof o.summary_field === 'string' && o.summary_field) ||
    firstFieldByType(fields, ['longtext'])
  const dateField =
    (typeof o.date_field === 'string' && o.date_field) ||
    firstFieldByType(fields, ['date', 'datetime'])
  const cardSize = CARD_SIZES.includes(o.card_size as GalleryCardSize)
    ? (o.card_size as GalleryCardSize)
    : 'medium'
  const summaryLines = SUMMARY_LINE_OPTIONS.includes(o.summary_lines as GallerySummaryLines)
    ? (o.summary_lines as GallerySummaryLines)
    : 3
  return {
    titleField,
    summaryField,
    dateField,
    tagFields: asStringArray(o.tag_fields),
    metaFields: asStringArray(o.meta_fields),
    cardSize,
    summaryLines,
  }
}

// ── 标签归一 ──────────────────────────────────────────

/** 把单个标签字段的值归一为显示文本数组.
 *
 * - select：取 option label（未命中 option 时原样返回）
 * - multiselect：逐项取 option label（兼容逗号分隔串与数组）
 * - 其余类型（text 等）：原样字符串
 * - 空值剔除
 */
export function galleryTagLabels(field: Field, value: unknown): string[] {
  if (value === null || value === undefined || value === '') return []
  const ft = field.field_type
  if (ft === 'select') {
    const label = getSelectLabel(field, value).trim()
    return label ? [label] : []
  }
  if (ft === 'multiselect' || ft === 'multi_select') {
    return formatMultiSelectValue(value)
      .map((v) => getSelectLabel(field, v).trim())
      .filter(Boolean)
  }
  return [String(value).trim()].filter(Boolean)
}

/** 汇总单卡所有标签字段的值，并应用单卡上限（超出部分以 overflow 返回，由 UI 渲染 `+N`）.
 *
 * 字段不存在（已删除 / 脏引用）时跳过；同一字段多值会各占一个标签位。
 */
export function galleryCardTags(
  row: RowResponse,
  fields: Field[],
  tagFields: string[],
  max = GALLERY_MAX_TAGS,
): { tags: GalleryTagItem[]; overflow: number } {
  const all: GalleryTagItem[] = []
  for (const name of tagFields) {
    const field = fields.find((f) => f.name === name)
    if (!field) continue
    for (const label of galleryTagLabels(field, row[name])) {
      all.push({ label, field })
    }
  }
  return { tags: all.slice(0, max), overflow: Math.max(0, all.length - max) }
}

// ── 元信息 ────────────────────────────────────────────

/** 提取卡片底部元信息：复用 formatFieldDisplayValue，空值跳过，最多 4 项（保持 metaFields 顺序） */
export function galleryMetaItems(
  fields: Field[],
  row: RowResponse,
  metaFields: string[],
  max = GALLERY_MAX_META,
): GalleryMetaItem[] {
  const out: GalleryMetaItem[] = []
  for (const name of metaFields) {
    if (out.length >= max) break
    const field = fields.find((f) => f.name === name)
    if (!field) continue
    const text = formatFieldDisplayValue(field, row[name]).trim()
    if (!text) continue
    out.push({ field, label: field.name, text })
  }
  return out
}

// ── 卡片文本 ──────────────────────────────────────────

/** 卡片标题：title_field 的原始值；空值回退 `#id`（配置层已保证 titleField 有值） */
export function galleryCardTitle(row: RowResponse, titleField: string): string {
  const v = row[titleField]
  if (v === null || v === undefined || v === '') return `#${row.id}`
  return String(v)
}

/** 卡片摘要：summary_field 的原始文本（保留换行，由 CSS line-clamp 截断）；未配置返回空串 */
export function gallerySummaryText(row: RowResponse, summaryField?: string): string {
  if (!summaryField) return ''
  const v = row[summaryField]
  if (v === null || v === undefined) return ''
  return String(v).trim()
}

/** 日期徽章：取前 10 位（date / datetime 统一显示 YYYY-MM-DD）；空值返回空串 */
export function galleryDateBadge(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  return String(value).slice(0, 10)
}

/** 标签取色用的原始 options（select/multiselect 字段配置；其他类型返回 undefined） */
export function galleryTagOptions(field: Field): unknown {
  const ft = field.field_type
  if (ft !== 'select' && ft !== 'multiselect' && ft !== 'multi_select') return undefined
  return extractSelectOptions(field.config)
}

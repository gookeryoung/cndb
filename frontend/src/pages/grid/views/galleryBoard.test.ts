/** galleryBoard 纯逻辑单元测试 —— 配置回退链、标签归一与上限、元信息提取、列宽映射 */
import { describe, expect, it } from 'vitest'
import {
  GALLERY_BATCH_SIZE,
  GALLERY_COLUMN_MIN_PX,
  galleryCardTags,
  galleryCardTitle,
  galleryDateBadge,
  galleryMetaItems,
  gallerySummaryText,
  galleryTagLabels,
  resolveGalleryConfig,
} from './galleryBoard'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: 'title', field_type: 'text' }),
  makeField({ id: 2, name: 'summary', field_type: 'longtext' }),
  makeField({ id: 3, name: 'date', field_type: 'date' }),
  makeField({ id: 4, name: 'cuisine', field_type: 'select', config: { options: ['粤菜', '西餐'] } }),
  makeField({ id: 5, name: 'difficulty', field_type: 'select', config: { options: ['简单', '中等'] } }),
  makeField({ id: 6, name: 'cook_time_min', field_type: 'number' }),
]

const ROW = {
  id: 7,
  title: '南瓜蒸排骨',
  summary: '1.排骨斩小段泡水去血水；2.上汽蒸25分钟',
  date: '2026-10-22 08:30:00',
  cuisine: '粤菜',
  difficulty: '简单',
  cook_time_min: 40,
} as unknown as RowResponse

describe('resolveGalleryConfig 配置回退链', () => {
  it('显式配置原样保留', () => {
    const cfg = resolveGalleryConfig(FIELDS, {
      title_field: 'title',
      summary_field: 'summary',
      tag_fields: ['cuisine', 'difficulty'],
      meta_fields: ['cook_time_min'],
      date_field: 'date',
      card_size: 'large',
      summary_lines: 6,
    })
    expect(cfg).toEqual({
      titleField: 'title',
      summaryField: 'summary',
      dateField: 'date',
      tagFields: ['cuisine', 'difficulty'],
      metaFields: ['cook_time_min'],
      cardSize: 'large',
      summaryLines: 6,
    })
  })

  it('未配置时自动推断 title/summary/date', () => {
    const cfg = resolveGalleryConfig(FIELDS, {})
    expect(cfg.titleField).toBe('title') // 首个 text
    expect(cfg.summaryField).toBe('summary') // 首个 longtext
    expect(cfg.dateField).toBe('date') // 首个 date/datetime
    expect(cfg.tagFields).toEqual([])
    expect(cfg.metaFields).toEqual([])
    expect(cfg.cardSize).toBe('medium')
    expect(cfg.summaryLines).toBe(3)
  })

  it('title 回退链：无文本字段取首字段，无字段回退 id', () => {
    const noText = [makeField({ id: 1, name: 'num', field_type: 'number' })]
    expect(resolveGalleryConfig(noText, {}).titleField).toBe('num')
    expect(resolveGalleryConfig([], {}).titleField).toBe('id')
  })

  it('无 longtext / 日期字段时 summaryField / dateField 为空', () => {
    const cfg = resolveGalleryConfig([makeField({ id: 1, name: 't', field_type: 'text' })], {})
    expect(cfg.summaryField).toBeUndefined()
    expect(cfg.dateField).toBeUndefined()
  })

  it('tag_fields / meta_fields 非数组按空处理（兼容历史脏值）', () => {
    const cfg = resolveGalleryConfig(FIELDS, { tag_fields: 'cuisine', meta_fields: { a: 1 } })
    expect(cfg.tagFields).toEqual([])
    expect(cfg.metaFields).toEqual([])
    const cfg2 = resolveGalleryConfig(FIELDS, { tag_fields: ['cuisine', 42, ''], meta_fields: null })
    expect(cfg2.tagFields).toEqual(['cuisine'])
    expect(cfg2.metaFields).toEqual([])
  })

  it('card_size / summary_lines 非法值回退 medium / 3', () => {
    const cfg = resolveGalleryConfig(FIELDS, { card_size: 'huge', summary_lines: 5 })
    expect(cfg.cardSize).toBe('medium')
    expect(cfg.summaryLines).toBe(3)
  })
})

describe('galleryTagLabels 标签归一', () => {
  const cuisine = FIELDS.find((f) => f.name === 'cuisine')!
  const difficulty = FIELDS.find((f) => f.name === 'difficulty')!

  it('select 取 option label', () => {
    expect(galleryTagLabels(cuisine, '粤菜')).toEqual(['粤菜'])
    // 值不在 options 中时原样返回
    expect(galleryTagLabels(cuisine, '川菜')).toEqual(['川菜'])
  })

  it('multiselect 逐项取 label（数组与逗号串均可）', () => {
    const multi = makeField({ id: 8, name: 'tags', field_type: 'multiselect', config: { options: ['a', 'b', 'c'] } })
    expect(galleryTagLabels(multi, ['a', 'c'])).toEqual(['a', 'c'])
    expect(galleryTagLabels(multi, 'a,b')).toEqual(['a', 'b'])
  })

  it('text 原样返回，空值剔除', () => {
    const text = FIELDS.find((f) => f.name === 'title')!
    expect(galleryTagLabels(text, '突发')).toEqual(['突发'])
    expect(galleryTagLabels(difficulty, '')).toEqual([])
    expect(galleryTagLabels(difficulty, null)).toEqual([])
    expect(galleryTagLabels(text, '   ')).toEqual([])
  })
})

describe('galleryCardTags 单卡标签上限', () => {
  it('跨字段汇总，超过 6 个时截断并返回 overflow', () => {
    const multi = makeField({
      id: 9, name: 'many', field_type: 'multiselect',
      config: { options: ['t1', 't2', 't3', 't4', 't5'] },
    })
    const fields = [...FIELDS, multi]
    const row = { ...ROW, many: ['t1', 't2', 't3', 't4', 't5'] } as unknown as RowResponse
    const { tags, overflow } = galleryCardTags(row, fields, ['cuisine', 'difficulty', 'many'])
    expect(tags).toHaveLength(6)
    expect(tags.map((t) => t.label)).toEqual(['粤菜', '简单', 't1', 't2', 't3', 't4'])
    expect(overflow).toBe(1)
  })

  it('字段不存在时跳过，不产生标签', () => {
    const { tags, overflow } = galleryCardTags(ROW, FIELDS, ['missing', 'cuisine'])
    expect(tags.map((t) => t.label)).toEqual(['粤菜'])
    expect(overflow).toBe(0)
  })

  it('空值字段不占标签位', () => {
    const row = { ...ROW, cuisine: null, difficulty: '' } as unknown as RowResponse
    const { tags, overflow } = galleryCardTags(row, FIELDS, ['cuisine', 'difficulty'])
    expect(tags).toEqual([])
    expect(overflow).toBe(0)
  })
})

describe('galleryMetaItems 元信息', () => {
  it('按配置顺序提取并格式化，空值跳过', () => {
    const row = { ...ROW, cuisine: null } as unknown as RowResponse
    const items = galleryMetaItems(FIELDS, row, ['cook_time_min', 'cuisine', 'date'])
    expect(items.map((i) => `${i.label}：${i.text}`)).toEqual([
      'cook_time_min：40',
      'date：2026-10-22 08:30:00',
    ])
  })

  it('最多 4 项', () => {
    const fields = [
      ...FIELDS,
      makeField({ id: 10, name: 'extra1', field_type: 'text' }),
      makeField({ id: 11, name: 'extra2', field_type: 'text' }),
      makeField({ id: 12, name: 'extra3', field_type: 'text' }),
    ]
    const row = { ...ROW, extra1: 'x', extra2: 'y', extra3: 'z' } as unknown as RowResponse
    const items = galleryMetaItems(fields, row, ['title', 'cook_time_min', 'extra1', 'extra2', 'extra3'])
    expect(items).toHaveLength(4)
  })

  it('字段不存在时跳过', () => {
    expect(galleryMetaItems(FIELDS, ROW, ['missing'])).toEqual([])
  })
})

describe('卡片文本与常量', () => {
  it('galleryCardTitle 空值回退 #id', () => {
    expect(galleryCardTitle(ROW, 'title')).toBe('南瓜蒸排骨')
    expect(galleryCardTitle({ id: 9, title: '' } as unknown as RowResponse, 'title')).toBe('#9')
  })

  it('gallerySummaryText 去除首尾空白，未配置返回空串', () => {
    expect(gallerySummaryText(ROW, 'summary')).toBe('1.排骨斩小段泡水去血水；2.上汽蒸25分钟')
    expect(gallerySummaryText(ROW, undefined)).toBe('')
    expect(gallerySummaryText({ id: 1, s: null } as unknown as RowResponse, 's')).toBe('')
  })

  it('galleryDateBadge 取前 10 位', () => {
    expect(galleryDateBadge('2026-10-22 08:30:00')).toBe('2026-10-22')
    expect(galleryDateBadge('')).toBe('')
    expect(galleryDateBadge(null)).toBe('')
  })

  it('批次与列宽常量', () => {
    expect(GALLERY_BATCH_SIZE).toBe(48)
    expect(GALLERY_COLUMN_MIN_PX).toEqual({ small: 220, medium: 280, large: 360 })
  })
})

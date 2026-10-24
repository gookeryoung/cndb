/** 文档格式映射表测试（ADR 0025）：形状 + 配色唯一、原件族判定、未知回退. */

import { describe, expect, it } from 'vitest'
import {
  DOC_ASSET_CONTENT_TYPES,
  DOC_FORMAT_META,
  formatMeta,
  isAssetContentType,
} from './docFormat'

describe('docFormat 格式映射', () => {
  it('每种格式都有标签 / 图标 / 配色，且配色不与其它格式重复', () => {
    const colors = Object.values(DOC_FORMAT_META).map(meta => meta.color)
    // 文件夹色与格式色可并列，但各格式之间必须互不相同
    const docColors = colors.filter((_, idx) => Object.keys(DOC_FORMAT_META)[idx] !== 'folder')
    expect(new Set(docColors).size).toBe(docColors.length)
    for (const [key, meta] of Object.entries(DOC_FORMAT_META)) {
      expect(meta.label, key).toBeTruthy()
      expect(meta.Icon, key).toBeTruthy()
      expect(meta.color, key).toBeTruthy()
    }
  })

  it('原件族格式（pdf / image / xlsx / pptx）标记为只读', () => {
    for (const type of DOC_ASSET_CONTENT_TYPES) {
      expect(formatMeta(type).asset).toBe(true)
      expect(isAssetContentType(type)).toBe(true)
    }
    expect(formatMeta('markdown').asset).toBe(false)
    expect(isAssetContentType('markdown')).toBe(false)
    expect(isAssetContentType()).toBe(false)
  })

  it('文件夹优先走文件夹图标（即使 content_type 异常）', () => {
    expect(formatMeta('pdf', true).label).toBe('文件夹')
  })

  it('未知 / 空 content_type 回退通用文件图标', () => {
    for (const value of [undefined, null, '', 'unknown-format']) {
      const meta = formatMeta(value)
      expect(meta.label).toBe('文档')
      expect(meta.asset).toBe(false)
    }
  })

  it('大小写不敏感', () => {
    expect(formatMeta('PDF').label).toBe('PDF')
    expect(isAssetContentType('IMAGE')).toBe(true)
  })
})

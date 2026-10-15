/** documentStats 纯函数测试 —— 正文字数 / 行数 / 阅读时长. */

import { describe, expect, it } from 'vitest'

import { READING_SPEED_CPM, documentStats, formatStatsLabel } from './documentStats'

describe('documentStats', () => {
  it('空文本全部为 0', () => {
    expect(documentStats('')).toEqual({
      chars: 0, charsNoSpace: 0, lines: 0, paragraphs: 0, readingMinutes: 0,
    })
  })

  it('统计字符数、剔除空白的字符数、行数与段落数', () => {
    const stats = documentStats('# 标题\n\n正文 段落\n\n')
    // '# 标题\n\n正文 段落\n\n'：13 个字符（含 6 个空白）、5 行、2 个非空段落
    expect(stats.chars).toBe(13)
    expect(stats.charsNoSpace).toBe(7)
    expect(stats.lines).toBe(5)
    expect(stats.paragraphs).toBe(2)
  })

  it('阅读时长按 300 字/分钟向上取整', () => {
    expect(documentStats('字'.repeat(300)).readingMinutes).toBe(1)
    expect(documentStats('字'.repeat(301)).readingMinutes).toBe(2)
    expect(READING_SPEED_CPM).toBe(300)
  })

  it('纯空白文本不计阅读时长，但计入字符数与行数', () => {
    const stats = documentStats('   \n  ')
    expect(stats.charsNoSpace).toBe(0)
    expect(stats.readingMinutes).toBe(0)
    expect(stats.paragraphs).toBe(0)
    expect(stats.lines).toBe(2)
  })

  it('单行无换行符时行数为 1', () => {
    expect(documentStats('abc').lines).toBe(1)
  })
})

describe('formatStatsLabel', () => {
  it('组合字数 / 行数 / 阅读时长', () => {
    expect(formatStatsLabel(documentStats('字'.repeat(301)))).toBe('301 字 · 1 行 · 约 2 分钟')
  })

  it('千位分隔并在无内容时省略阅读时长', () => {
    expect(formatStatsLabel(documentStats(''))).toBe('0 字 · 0 行')
    expect(formatStatsLabel({ chars: 12345, charsNoSpace: 12345, lines: 20, paragraphs: 3, readingMinutes: 42 }))
      .toBe('12,345 字 · 20 行 · 约 42 分钟')
  })
})

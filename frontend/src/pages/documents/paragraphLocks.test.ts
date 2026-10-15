/**
 * 段落定位工具测试 —— 与后端切分规则一致性.
 */

import { describe, expect, it } from 'vitest'
import {
  keyToIndex,
  offsetOfParagraph,
  paragraphIndexAtOffset,
  paragraphKeys,
  splitParagraphs,
} from './paragraphLocks'

const DOC = '# 标题\n\n第一段\n\n第二段\n\n第三段\n'

describe('splitParagraphs', () => {
  it('按空行切分并去空块', () => {
    expect(splitParagraphs(DOC)).toEqual(['# 标题', '第一段', '第二段', '第三段'])
  })

  it('兼容 CRLF 与连续空行', () => {
    expect(splitParagraphs('A\r\n\r\n\r\nB\r\n')).toEqual(['A', 'B'])
  })

  it('保留段内换行', () => {
    expect(splitParagraphs('l1\nl2\n\nnext')).toEqual(['l1\nl2', 'next'])
  })

  it('空文本返回空数组', () => {
    expect(splitParagraphs('')).toEqual([])
    expect(splitParagraphs('  \n\n ')).toEqual([])
  })
})

describe('paragraphKeys / keyToIndex', () => {
  it('位置键 p1..pn', () => {
    expect(paragraphKeys(DOC)).toEqual(['p1', 'p2', 'p3', 'p4'])
  })

  it('键解析', () => {
    expect(keyToIndex('p3')).toBe(3)
    expect(keyToIndex('p0')).toBeNull()
    expect(keyToIndex('x1')).toBeNull()
  })
})

describe('paragraphIndexAtOffset', () => {
  it('光标在第 2 段（"第一段"）内', () => {
    const offset = DOC.indexOf('第一段') + 1
    expect(paragraphIndexAtOffset(DOC, offset)).toBe(2)
  })

  it('光标在标题段', () => {
    expect(paragraphIndexAtOffset(DOC, 2)).toBe(1)
  })

  it('落在段落分隔空行上不归属任何段', () => {
    // "\n\n" 的第一行的位置属于上一段的收尾；用纯空行段落测试
    expect(paragraphIndexAtOffset('\n\n', 0)).toBeNull()
  })

  it('非法偏移返回 null', () => {
    expect(paragraphIndexAtOffset('', 0)).toBeNull()
    expect(paragraphIndexAtOffset('abc', -1)).toBeNull()
  })
})

describe('offsetOfParagraph', () => {
  it('返回该段起始偏移，可用于跳转', () => {
    const offset = offsetOfParagraph(DOC, 3)
    expect(offset).not.toBeNull()
    expect(DOC.slice(offset!)).toMatch(/^第二段/)
  })

  it('越界返回 null', () => {
    expect(offsetOfParagraph(DOC, 0)).toBeNull()
    expect(offsetOfParagraph(DOC, 99)).toBeNull()
  })
})

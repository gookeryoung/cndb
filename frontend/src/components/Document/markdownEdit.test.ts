/** markdownEdit 纯函数测试 —— 编辑器 Markdown 快捷操作. */

import { describe, expect, it } from 'vitest'

import {
  insertLink,
  toggleHeading,
  toggleLinePrefix,
  toggleOrderedList,
  wrapCodeBlock,
  wrapSelection,
} from './markdownEdit'

describe('wrapSelection', () => {
  it('选中文本两侧加粗，选区仍在文字上', () => {
    const r = wrapSelection('前半 后半', 3, 5, '**')
    expect(r.value).toBe('前半 **后半**')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('后半')
  })

  it('无选中时插入占位并选中占位文本', () => {
    const r = wrapSelection('abc', 1, 1, '*')
    expect(r.value).toBe('a*文本*bc')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('文本')
  })

  it('选区内已含标记时再次点击取消', () => {
    const r = wrapSelection('a **b** c', 2, 7, '**')
    expect(r.value).toBe('a b c')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('b')
  })

  it('选区紧贴外侧标记时取消（光标只选中文字的情形）', () => {
    const r = wrapSelection('a **b** c', 4, 5, '**')
    expect(r.value).toBe('a b c')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('b')
  })

  it('行内代码用同一标记作为前后缀', () => {
    const r = wrapSelection('let x = 1', 0, 9, '`')
    expect(r.value).toBe('`let x = 1`')
  })

  it('越界/倒置选区被归一化，不抛错', () => {
    expect(() => wrapSelection('abc', 99, -5, '**')).not.toThrow()
    expect(wrapSelection('abc', 99, -5, '**').value).toBe('abc**文本**')
  })
})

describe('toggleLinePrefix（无序列表 / 引用）', () => {
  it('单行加前缀，并选中整行', () => {
    const r = toggleLinePrefix('第一行\n第二行', 0, 0, '- ')
    expect(r.value).toBe('- 第一行\n第二行')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('- 第一行')
  })

  it('多行补齐缺失前缀（部分已有时不重复加）', () => {
    const r = toggleLinePrefix('- a\nb', 0, 5, '- ')
    expect(r.value).toBe('- a\n- b')
  })

  it('所选行全部已带前缀时再点一次移除（幂等切换）', () => {
    const r = toggleLinePrefix('- a\n- b', 0, 7, '- ')
    expect(r.value).toBe('a\nb')
  })

  it('引用前缀同样支持切换', () => {
    const once = toggleLinePrefix('正文', 0, 2, '> ')
    expect(once.value).toBe('> 正文')
    const twice = toggleLinePrefix(once.value, once.selectionStart, once.selectionEnd, '> ')
    expect(twice.value).toBe('正文')
  })

  it('跨多行的选区整体处理', () => {
    // 选区覆盖 b、c 两行（偏移 2..4）
    const r = toggleLinePrefix('a\nb\nc', 2, 4, '- ')
    expect(r.value).toBe('a\n- b\n- c')
  })
})

describe('toggleOrderedList', () => {
  it('按行重新编号', () => {
    const r = toggleOrderedList('甲\n乙\n丙', 0, 5)
    expect(r.value).toBe('1. 甲\n2. 乙\n3. 丙')
  })

  it('全部已编号时移除编号', () => {
    const r = toggleOrderedList('1. 甲\n2. 乙', 0, 8)
    expect(r.value).toBe('甲\n乙')
  })

  it('混合状态时统一重排编号', () => {
    const r = toggleOrderedList('1. 甲\n乙', 0, 5)
    expect(r.value).toBe('1. 甲\n2. 乙')
  })
})

describe('toggleHeading', () => {
  it('设为二级标题', () => {
    const r = toggleHeading('标题', 0, 2, 2)
    expect(r.value).toBe('## 标题')
  })

  it('同级再点取消为普通段落', () => {
    const r = toggleHeading('## 标题', 0, 6, 2)
    expect(r.value).toBe('标题')
  })

  it('换级别时替换既有级别', () => {
    const r = toggleHeading('# 标题', 0, 5, 3)
    expect(r.value).toBe('### 标题')
  })

  it('多行统一处理', () => {
    const r = toggleHeading('a\nb', 0, 3, 1)
    expect(r.value).toBe('# a\n# b')
  })
})

describe('wrapCodeBlock', () => {
  it('选中内容包裹为围栏代码块并保留语言标记', () => {
    const r = wrapCodeBlock('前\ncode\n后', 2, 6, 'ts')
    expect(r.value).toBe('前\n```ts\ncode\n```\n后')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('code')
  })

  it('无选中时插入空代码块，光标在正文行', () => {
    const r = wrapCodeBlock('', 0, 0)
    expect(r.value).toBe('```\n\n```')
    expect(r.selectionStart).toBe(4)
    expect(r.selectionEnd).toBe(4)
  })

  it('紧贴文本插入时自动补换行，保证围栏独占行', () => {
    const r = wrapCodeBlock('abc', 3, 3)
    expect(r.value).toBe('abc\n```\n\n```')
  })
})

describe('insertLink', () => {
  it('选中文本作为链接文字，光标选中 URL 便于粘贴', () => {
    const r = insertLink('见 文档', 2, 4)
    expect(r.value).toBe('见 [文档](https://)')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('https://')
  })

  it('无选中时使用占位文字', () => {
    const r = insertLink('', 0, 0, '标题', 'https://example.com')
    expect(r.value).toBe('[标题](https://example.com)')
    expect(r.value.slice(r.selectionStart, r.selectionEnd)).toBe('https://example.com')
  })
})

/** 列表回车命令测试：延续标记但不额外插入空行（loose list / 空项）。 */

import { describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { markdown } from '@codemirror/lang-markdown'
import { collapseBlankLine, continueMarkupSingleLine } from './markdownEnter'

function run(doc: string, pos: number) {
  const state = EditorState.create({
    doc,
    selection: EditorSelection.cursor(pos),
    extensions: [markdown()],
  })
  let next: EditorState | null = null
  const handled = continueMarkupSingleLine()({
    state,
    dispatch: tr => {
      next = tr.state
    },
  })
  const result = next as EditorState | null
  return {
    handled,
    doc: result ? result.doc.toString() : doc,
    head: result ? result.selection.main.head : pos,
  }
}

describe('collapseBlankLine', () => {
  it('把「空行 + 换行」收成单个换行，保留缩进与引用符', () => {
    expect(collapseBlankLine('\n\n- ')).toBe('\n- ')
    expect(collapseBlankLine('\n  \n  - ')).toBe('\n  - ')
    expect(collapseBlankLine('\n> \n> - ')).toBe('\n> - ')
    expect(collapseBlankLine('\n- ')).toBe('\n- ')
    expect(collapseBlankLine('\n')).toBe('\n')
  })
})

describe('continueMarkupSingleLine 回车', () => {
  it('紧凑列表：只新增一行并延续标记', () => {
    const r = run('- aaa\n- bbb', 11)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('- aaa\n- bbb\n- ')
    expect(r.head).toBe(r.doc.length)
  })

  it('loose list（项间已有空行）在末尾回车：不再补空行', () => {
    const r = run('- aaa\n\n- bbb', 12)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('- aaa\n\n- bbb\n- ')
    expect(r.head).toBe(r.doc.length)
  })

  it('loose list 中间回车：新增行不加空行', () => {
    const r = run('- aaa\n\n- bbb', 10)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('- aaa\n\n- b\n- bb')
    expect(r.doc).not.toContain('\n\n- bb')
  })

  it('空项回车：清掉标记回到普通行，不多插空行', () => {
    const r = run('- aaa\n- ', 8)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('- aaa\n')
    expect(r.doc).not.toContain('\n\n')
  })

  it('待办列表延续复选框标记', () => {
    const r = run('- [ ] aaa', 9)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('- [ ] aaa\n- [ ] ')
  })

  it('有序列表：新项按序号续接', () => {
    const r = run('1. aaa', 4)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('1. a\n2. aa')
  })

  it('引用内的 loose 列表：收掉空行后引用符不丢', () => {
    const r = run('> - aaa\n>\n> - bbb', 17)
    expect(r.handled).toBe(true)
    expect(r.doc).toBe('> - aaa\n>\n> - bbb\n> - ')
  })

  it('非 Markdown 标记上下文返回 false（普通段落走默认回车）', () => {
    const r = run('hello world', 5)
    expect(r.handled).toBe(false)
    expect(r.doc).toBe('hello world')
  })
})

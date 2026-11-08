/** 结构 DSL 缩进与花括号对齐测试（需求卡 0127 C3 / C4）. */

import { describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { DSL_INDENT_UNIT, indentAt, insertDslNewline } from './designIndent'

/** 建一个仅用于缩进断言的最小编辑器视图 */
function viewOf(doc: string, selection: { anchor: number; head?: number } = { anchor: doc.length }): EditorView {
  return new EditorView({
    state: EditorState.create({ doc, selection }),
  })
}

/** 在视图上执行一次智能回车 */
function enter(view: EditorView): string {
  insertDslNewline(view)
  return view.state.doc.toString()
}

describe('designIndent 缩进口径（C3）', () => {
  it('固定 2 空格', () => {
    expect(DSL_INDENT_UNIT).toBe('  ')
    expect(DSL_INDENT_UNIT).not.toContain('\t')
  })

  it('按花括号深度计算行缩进：块内 +2、闭合行回退一层', () => {
    const doc = [
      'module plate(d = 10) {',
      '  box(size = [d, d, d])',
      '}',
    ].join('\n')
    expect(indentAt(doc, doc.indexOf('  box'))).toBe(2)
    expect(indentAt(doc, doc.lastIndexOf('\n}') + 1)).toBe(0)
  })

  it('嵌套布尔块逐层加级', () => {
    const doc = [
      'module plate(d = 10) {',
      '  union {',
      '    box(size = [d, d, d])',
      '  }',
      '}',
    ].join('\n')
    expect(indentAt(doc, doc.indexOf('    box'))).toBe(4)
    expect(indentAt(doc, doc.indexOf('  }'))).toBe(2)
  })

  it('字符串与注释里的花括号不计入深度', () => {
    const doc = [
      'param s = "{"',
      '// {',
      '/* } */',
      'box(size = [1, 1, 1])',
    ].join('\n')
    expect(indentAt(doc, doc.indexOf('box'))).toBe(0)
  })
})

describe('designIndent 智能回车（C4）', () => {
  it('行尾 { 回车进入下一层', () => {
    const view = viewOf('module plate(d = 10) {')
    try {
      expect(enter(view)).toBe('module plate(d = 10) {\n  ')
    } finally {
      view.destroy()
    }
  })

  it('自动配对 {} 之间回车展开三行，右花括号对齐', () => {
    const doc = 'module plate(d = 10) {}'
    const view = viewOf(doc, { anchor: doc.length - 1 })
    try {
      expect(enter(view)).toBe('module plate(d = 10) {\n  \n}')
      expect(view.state.selection.main.head).toBe('module plate(d = 10) {\n  '.length)
    } finally {
      view.destroy()
    }
  })

  it('空行回车继承当前缩进，不自动回退', () => {
    const doc = 'module plate(d = 10) {\n  '
    const view = viewOf(doc)
    try {
      expect(enter(view)).toBe(`${doc}\n  `)
    } finally {
      view.destroy()
    }
  })

  it('非空选区回车只替换选区，不套用缩进', () => {
    const view = viewOf('abc', { anchor: 0, head: 2 })
    try {
      expect(enter(view)).toBe('\nc')
    } finally {
      view.destroy()
    }
  })
})

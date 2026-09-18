/** jinja2Highlight 单元测试 —— 三类 token 识别与 DecorationSet 构建 */
import { EditorState } from '@codemirror/state'
import type { DecorationSet } from '@codemirror/view'
import { describe, expect, it } from 'vitest'
import { jinja2StateField } from './jinja2Highlight'

/** 构建编辑器状态并返回其 DecorationSet 与文档文本 */
function buildDecos(text: string): DecorationSet {
  const state = EditorState.create({ doc: text, extensions: [jinja2StateField] })
  return state.field(jinja2StateField)
}

/** 把 DecorationSet 摊平为 [{from, to, class}] 数组便于断言 */
function flatten(decos: DecorationSet): Array<{ from: number; to: number; cls: string }> {
  const out: Array<{ from: number; to: number; cls: string }> = []
  const iter = decos.iter()
  while (iter.value) {
    const spec = (iter.value.spec ?? {}) as { class?: string }
    out.push({ from: iter.from, to: iter.to, cls: spec.class ?? '' })
    iter.next()
  }
  return out
}

describe('jinja2StateField token 识别', () => {
  it('{{ }} 变量标记为 cm-jinja-variable', () => {
    const decos = buildDecos('Hello {{ name }}!')
    expect(flatten(decos)).toEqual([{ from: 6, to: 16, cls: 'cm-jinja-variable' }])
  })

  it('{% %} 语句标记为 cm-jinja-statement', () => {
    const text = '{% if x %}yes{% endif %}'
    const items = flatten(buildDecos(text))
    expect(items).toHaveLength(2)
    expect(items.every((i) => i.cls === 'cm-jinja-statement')).toBe(true)
    expect(items[0]).toEqual({ from: text.indexOf('{%'), to: text.indexOf('%}') + 2, cls: 'cm-jinja-statement' })
  })

  it('{# #} 注释标记为 cm-jinja-comment', () => {
    const text = '{# 注释 #}'
    expect(flatten(buildDecos(text))).toEqual([
      { from: 0, to: text.length, cls: 'cm-jinja-comment' },
    ])
  })

  it('混排文本：变量/语句/注释与普通文本混合定位准确', () => {
    const text = 'A{{ v }}B{% if %}C{# c #}D'
    const items = flatten(buildDecos(text))
    expect(items).toHaveLength(3)
    expect(items[0]).toEqual({ from: text.indexOf('{{'), to: text.indexOf('}}') + 2, cls: 'cm-jinja-variable' })
    expect(items[1]).toEqual({ from: text.indexOf('{%'), to: text.indexOf('%}') + 2, cls: 'cm-jinja-statement' })
    expect(items[2]).toEqual({ from: text.indexOf('{#'), to: text.indexOf('#}') + 2, cls: 'cm-jinja-comment' })
  })

  it('无 token 的纯文本产生空 DecorationSet', () => {
    const decos = buildDecos('plain text without any template tokens')
    expect(flatten(decos)).toEqual([])
  })

  it('空文档产生空 DecorationSet', () => {
    expect(flatten(buildDecos(''))).toEqual([])
  })

  it('未闭合的标记不产生装饰（需完整闭合对）', () => {
    expect(flatten(buildDecos('{{ open'))).toEqual([])
    expect(flatten(buildDecos('{% open'))).toEqual([])
  })

  it('生成的是 mark 装饰（spec 带 class，无 widget/block 标记）', () => {
    const decos = buildDecos('{{ x }}')
    const iter = decos.iter()
    expect(iter.value).toBeTruthy()
    // @codemirror/view 的 Decoration 无公开 type 字段；
    // mark 装饰的特征是 spec 携带 class 且不含 widget（widget 装饰）或 block（行装饰）
    const spec = iter.value!.spec as { class?: string; widget?: unknown; block?: boolean }
    expect(spec.class).toBe('cm-jinja-variable')
    expect(spec.widget).toBeUndefined()
    expect(spec.block).toBeUndefined()
  })
})

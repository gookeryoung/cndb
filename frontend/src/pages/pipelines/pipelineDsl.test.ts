/** 流水线 DSL 语言支持测试（需求卡 0111 C2 / C3）.
 *
 * 关键字 / 严重度常量按后端 `parse.py` 的 `_TOP_KEYS / _ON_KEYS / _JOB_KEYS /
 * _STEP_KEYS` 与 `models.SEVERITIES` 硬编码比对（C2 单一来源）。
 */

import { describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import {
  DSL_KEYWORDS,
  JOB_KEYWORDS,
  KEYWORD_DETAILS,
  ON_KEYWORDS,
  SEVERITIES,
  STEP_KEYWORDS,
  TOP_KEYWORDS,
  insertDslNewline,
} from './pipelineDsl'

/** 最小编辑器视图（jsdom 下挂 DOM 才能 dispatch 选中位置） */
function makeView(doc: string, cursor = doc.length): EditorView {
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  return new EditorView({
    parent,
    state: EditorState.create({ doc, selection: { anchor: cursor } }),
  })
}

function pressEnter(view: EditorView) {
  insertDslNewline(view)
  return view.state.doc.toString()
}

describe('pipelineDsl 关键字口径（C2）', () => {
  it('四组键与后端 parse.py 逐项一致', () => {
    expect(TOP_KEYWORDS).toEqual(['name', 'on', 'vars', 'jobs'])
    expect(ON_KEYWORDS).toEqual(['manual', 'events', 'schedule'])
    expect(JOB_KEYWORDS).toEqual(['needs', 'if', 'steps'])
    expect(STEP_KEYWORDS).toEqual(['uses', 'with', 'severity', 'continue-on-error'])
    expect(DSL_KEYWORDS).toEqual([
      'name', 'on', 'vars', 'jobs',
      'manual', 'events', 'schedule',
      'needs', 'if', 'steps',
      'uses', 'with', 'severity', 'continue-on-error',
    ])
  })

  it('严重度取值与 models.SEVERITIES 一致', () => {
    expect(SEVERITIES).toEqual(['error', 'warn', 'info'])
  })

  it('每个关键字都有中文一句话（补全 detail，C4）', () => {
    for (const keyword of [...DSL_KEYWORDS, ...SEVERITIES]) {
      expect(KEYWORD_DETAILS[keyword]).toBeTruthy()
    }
  })
})

describe('pipelineDsl 自动缩进（C3）', () => {
  it('回车继承当前行缩进', () => {
    const view = makeView('jobs:\n  体检: x')
    expect(pressEnter(view)).toBe('jobs:\n  体检: x\n  ')
    view.destroy()
  })

  it('映射键结尾回车进入下一层（YAML 2 空格）', () => {
    const view = makeView('jobs:')
    expect(pressEnter(view)).toBe('jobs:\n  ')
    view.destroy()
  })

  it('列表行回车延续 `- ` 前缀（与 buildStepSnippet 6 空格同口径）', () => {
    const view = makeView('      - uses: table/null-rate')
    expect(pressEnter(view)).toBe('      - uses: table/null-rate\n      - ')
    view.destroy()
  })

  it('在缩进中间回车只继承空白，不复制内容', () => {
    const doc = '    steps:'
    const view = makeView(doc)
    expect(pressEnter(view)).toBe('    steps:\n      ')
    view.destroy()
  })

  it('列表项内的映射块按内容列进一级（`- with:` → 10 空格）', () => {
    const view = makeView('      - with:')
    expect(pressEnter(view)).toBe('      - with:\n          ')
    view.destroy()
  })

  it('裸列表短横回车进入列表项内容层', () => {
    const view = makeView('      -')
    expect(pressEnter(view)).toBe('      -\n        ')
    view.destroy()
  })

  it('空行回车回退一级缩进', () => {
    const view = makeView('jobs:\n      ')
    expect(pressEnter(view)).toBe('jobs:\n      \n    ')
    view.destroy()
  })

  it('行尾注释不影响冒号判定的进级', () => {
    const view = makeView('    steps: # 检查步骤列表')
    expect(pressEnter(view)).toBe('    steps: # 检查步骤列表\n      ')
    view.destroy()
  })

  it('纯注释行回车继承当前缩进，不按空行回退', () => {
    const view = makeView('    # 说明')
    expect(pressEnter(view)).toBe('    # 说明\n    ')
    view.destroy()
  })

  it('非空选区回车只替换选区，不猜缩进', () => {
    const view = makeView('jobs:\n  a: b', 8)
    view.dispatch({ selection: { anchor: 5, head: 8 } })
    expect(pressEnter(view)).toBe('jobs:\na: b')
    view.destroy()
  })
})

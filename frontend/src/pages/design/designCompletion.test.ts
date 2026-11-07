/** 结构 DSL 自动完成测试（需求卡 0110 C1-C4 / C10）.
 *
 * 补全源是纯函数（`CompletionContext` + 文档文本），不依赖 DOM；
 * 用 `|` 标记光标位构造 `CompletionContext`，逐项断言候选分流。
 */

import { describe, expect, it, vi } from 'vitest'
import { CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import { EditorState } from '@codemirror/state'
import {
  DSL_KEYWORDS,
  DSL_SNIPPET_TEMPLATES,
  PRIMITIVE_SIGNATURES,
  dslCompletionSource,
  dslSnippets,
  extractSymbols,
  findCallContext,
  stripCommentsAndStrings,
} from './designCompletion'

/** `|` 标记光标位（DSL 语法中不会出现该字符） */
function contextAt(docWithCursor: string, explicit = false): CompletionContext {
  const pos = docWithCursor.indexOf('|')
  const doc = docWithCursor.replace('|', '')
  const state = EditorState.create({ doc })
  return new CompletionContext(state, pos === -1 ? doc.length : pos, explicit)
}

async function optionsAt(docWithCursor: string, explicit = false) {
  const result = await dslCompletionSource(contextAt(docWithCursor, explicit))
  return result as CompletionResult | null
}

function labels(result: CompletionResult | null): string[] {
  return result ? result.options.map(option => option.label) : []
}

describe('designCompletion 关键字口径（C1）', () => {
  it('关键字补全与后端 parse.py 常量逐项一致', () => {
    expect(DSL_KEYWORDS).toEqual([
      'param', 'module', 'system', 'use', 'as', 'constraint',
      'union', 'difference', 'intersection',
      'translate', 'rotate', 'scale', 'mirror',
      'fixed', 'coincident', 'concentric', 'distance', 'angle',
    ])
  })

  it('图元命名参数与 _eval_* 一致', () => {
    expect(PRIMITIVE_SIGNATURES.box!.params).toEqual(['size', 'w', 'h', 'd'])
    expect(PRIMITIVE_SIGNATURES.cyl!.params).toEqual(['d', 'h', 'fn'])
    expect(PRIMITIVE_SIGNATURES.sphere!.params).toEqual(['r', 'fn'])
    expect(PRIMITIVE_SIGNATURES.cone!.params).toEqual(['d1', 'd2', 'h', 'fn'])
    expect(PRIMITIVE_SIGNATURES.torus!.params).toEqual(['r', 'tube', 'fn'])
    expect(PRIMITIVE_SIGNATURES.tube!.params).toEqual(['od', 'id', 'h', 'fn'])
  })
})

describe('designCompletion 片段（C4）', () => {
  it('六图元模板带签名与槽位', () => {
    expect(DSL_SNIPPET_TEMPLATES.box).toBe('box(size = [${1:10}, ${2:10}, ${3:10}])')
    expect(DSL_SNIPPET_TEMPLATES.cyl).toBe('cyl(d = ${1:10}, h = ${2:10})')
    expect(DSL_SNIPPET_TEMPLATES.sphere).toBe('sphere(r = ${1:5})')
    expect(DSL_SNIPPET_TEMPLATES.cone).toBe('cone(d1 = ${1:10}, d2 = ${2:5}, h = ${3:10})')
    expect(DSL_SNIPPET_TEMPLATES.torus).toBe('torus(r = ${1:10}, tube = ${2:2})')
    expect(DSL_SNIPPET_TEMPLATES.tube).toBe('tube(od = ${1:10}, id = ${2:6}, h = ${3:10})')
  })

  it('骨架片段覆盖 param / module / system / use / constraint 与四变换', () => {
    for (const name of ['param', 'module', 'system', 'use', 'constraint',
      'translate', 'rotate', 'scale', 'mirror']) {
      expect(DSL_SNIPPET_TEMPLATES[name]).toContain('${')
    }
    expect(dslSnippets.map(item => item.label)).toContain('box 片段')
    expect(dslSnippets.every(item => typeof item.apply === 'function')).toBe(true)
  })
})

describe('designCompletion 符号提取（C2）', () => {
  const DOC = [
    '// param fake = 1',
    'param width = 80',
    '/* module ghost(a) {',
    '  box(size = [1, 1, 1])',
    '} */',
    'module plate(d = 10, h = 2 * d) {',
    '  box(size = [d, d, h])',
    '}',
    'use "wheel"(d = 20) as wheel_a',
    'plate(d = 1) as plate_a',
  ].join('\n')

  it('剥离注释与字符串后提取 param / module 形参 / use 标签', () => {
    expect(extractSymbols(DOC)).toEqual({
      params: ['width'],
      modules: [{ name: 'plate', params: ['d', 'h'] }],
      labels: ['wheel_a'],
    })
  })

  it('stripCommentsAndStrings 等长替换并保留换行', () => {
    const stripped = stripCommentsAndStrings('// x\nparam a = 1 /* y */\nuse "k" as b')
    expect(stripped.split('\n')).toHaveLength(3)
    expect(stripped).not.toContain('x')
    expect(stripped).not.toContain('"k"')
    expect(stripped).toContain('param a = 1')
    expect(stripped).toContain('as b')
  })

  it('findCallContext 命中最近一层调用、向量内返回 null', () => {
    expect(findCallContext('plate(d', 'plate(d'.length)).toBe('plate')
    expect(findCallContext('box(size = [wi', 'box(size = [wi'.length)).toBeNull()
    expect(findCallContext('param a = ', 'param a = '.length)).toBeNull()
  })
})

describe('designCompletion 上下文分流（C3 / C5）', () => {
  const DOC = [
    'param width = 80',
    'module plate(d = 10, h = 20) {',
    '  box(size = [d, d, h])',
    '}',
    'use "wheel"(d = 20) as base',
  ].join('\n')

  it('无输入且非手动唤起时不返回候选', async () => {
    expect(await optionsAt(`${DOC}\nbox(`)).toBeNull()
  })

  it('顶层 / 行首出语句关键字、模块名与骨架片段', async () => {
    const result = await optionsAt(`${DOC}\npar`)
    expect(labels(result)).toEqual(expect.arrayContaining(['param', 'module', 'constraint', 'plate', 'box 片段']))
  })

  it('表达式位出参数、白名单函数与 PI', async () => {
    const result = await optionsAt('param width = 80\nparam height = |', true)
    const names = labels(result)
    expect(names).toEqual(expect.arrayContaining(['width', 'PI', 'sin', 'sqrt']))
    expect(names).not.toContain('box 片段')
  })

  it('向量内仍按表达式位补全', async () => {
    const result = await optionsAt('param width = 80\nbox(size = [wi|])')
    expect(labels(result)).toContain('width')
  })

  it('模块调用括号内只出该模块形参', async () => {
    const result = await optionsAt(`${DOC}\nplate(d|)`)
    expect(labels(result)).toEqual(['d', 'h'])
  })

  it('图元括号内出命名参数', async () => {
    const result = await optionsAt(`${DOC}\nbox(|)`, true)
    expect(labels(result)).toEqual(['size', 'w', 'h', 'd'])
  })

  it('constraint 行分流：类型位 / 锚点位 / 实例标签', async () => {
    expect(labels(await optionsAt(`${DOC}\nconstraint c1 fi`)))
      .toEqual(['fixed', 'coincident', 'concentric', 'distance', 'angle'])
    expect(labels(await optionsAt(`${DOC}\nconstraint c1 fixed(a = base.o|)`)))
      .toEqual(['origin', 'x', 'y', 'z'])
    expect(labels(await optionsAt(`${DOC}\nconstraint c1 fixed(a = |)`, true)))
      .toEqual(expect.arrayContaining(['fixed', 'base', 'origin']))
  })
})

describe('designCompletion 跨文件零件名（C10 / P2）', () => {
  const parts = [{ label: 'wheel', detail: '车轮（零件）' }, { label: 'axle', detail: '车轴（零件）' }]

  it('use 字符串位异步返回零件候选', async () => {
    const fetchParts = vi.fn().mockResolvedValue(parts)
    const doc = `param width = 80\nuse "wh|"`
    const result = await dslCompletionSource(contextAt(doc), { fetchParts })
    expect(fetchParts).toHaveBeenCalledTimes(1)
    expect(labels(result)).toEqual(['wheel', 'axle'])
    expect(result!.from).toBe(doc.replace('|', '').indexOf('"wh') + 1)
  })

  it('未注入获取函数或请求失败时静默降级为空候选', async () => {
    expect(await dslCompletionSource(contextAt('use "wh|'))).toBeNull()
    const result = await dslCompletionSource(contextAt('use "wh|'), {
      fetchParts: vi.fn().mockRejectedValue(new Error('network')),
    })
    expect(result).toBeNull()
  })
})

describe('复用模块库补全（ADR 0118 P1）', () => {
  const fetchLibrary = vi.fn(async () => [
    { moduleKey: 'flange', name: '法兰模块', latestVersion: 3 },
    { moduleKey: 'washer', name: '垫圈模块', latestVersion: 1 },
  ])

  it('use "lib: 位列出 key@最新版本', async () => {
    const result = await dslCompletionSource(contextAt('use "lib:|'), { fetchLibrary })
    expect(labels(result)).toEqual(['lib:flange@3', 'lib:washer@1'])
    expect(result?.options[0]?.detail).toBe('法兰模块 · v3')
    expect(fetchLibrary).toHaveBeenCalled()
  })

  it('lib: 前缀按 key / 名称过滤', async () => {
    const result = await dslCompletionSource(contextAt('use "lib:垫|'), { fetchLibrary })
    expect(labels(result)).toEqual(['lib:washer@1'])
  })

  it('lib:key@ 位提示最新版本号', async () => {
    const doc = 'use "lib:flange@|'
    const result = await dslCompletionSource(contextAt(doc), { fetchLibrary })
    expect(labels(result)).toEqual(['3'])
    expect(result?.from).toBe(doc.replace('|', '').length)
  })

  it('未注入 fetchLibrary 时静默不出候选', async () => {
    expect(await dslCompletionSource(contextAt('use "lib:|'))).toBeNull()
  })
})

/** 流水线 DSL 自动完成测试（需求卡 0111 C4-C7）.
 *
 * 补全源是纯函数（`CompletionContext` + 文档文本），用 `|` 标记光标位构造。
 */

import { describe, expect, it } from 'vitest'
import { CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import { EditorState } from '@codemirror/state'
import {
  currentJobId,
  extractPipelineSymbols,
  pipelineCompletionSource,
  type PipelineCheckLike,
} from './pipelineCompletion'

const CHECKS: PipelineCheckLike[] = [
  {
    uses: 'table/null-rate',
    title: '空值比例',
    category: 'table',
    severity: 'warn',
    target_types: ['table'],
    inputs: [
      { name: 'table', type: 'string', description: '目标表', required: true, default: null },
      { name: 'fields', type: 'array', description: '字段列表', required: true, default: null },
      { name: 'max_rate', type: 'number', description: '允许空值率', required: false, default: 0.2 },
    ],
  },
  {
    uses: 'document/broken-refs',
    title: '引用完整性',
    category: 'document',
    severity: 'warn',
    target_types: ['document'],
    inputs: [],
  },
]

/** `|` 标记光标位（流水线 DSL 中不会出现该字符） */
function contextAt(docWithCursor: string, explicit = false): CompletionContext {
  const pos = docWithCursor.indexOf('|')
  const doc = docWithCursor.replace('|', '')
  const state = EditorState.create({ doc })
  return new CompletionContext(state, pos === -1 ? doc.length : pos, explicit)
}

function optionsAt(
  docWithCursor: string,
  options: { checks?: readonly PipelineCheckLike[]; domain?: 'table' | 'document' } = {},
  explicit = false,
): CompletionResult | null {
  return pipelineCompletionSource(contextAt(docWithCursor, explicit), {
    checks: CHECKS,
    domain: 'table',
    ...options,
  })
}

function labels(result: CompletionResult | null): string[] {
  return result ? result.options.map(option => option.label) : []
}

const JOB_DOC = [
  'name: 巡检',
  'on:',
  '  manual: true',
  'jobs:',
  '  体检:',
  '    steps:',
  '      - uses: table/null-rate',
  '        with:',
  '          table: 人员',
].join('\n')

describe('pipelineCompletion 关键字分流（C4）', () => {
  it('顶层出 name / on / vars / jobs 与完整 workflow 骨架', () => {
    expect(labels(optionsAt('na|'))).toEqual(['name', 'on', 'vars', 'jobs', '流水线骨架'])
  })

  it('on 块出 manual / events / schedule', () => {
    expect(labels(optionsAt('on:\n  man|'))).toEqual(['manual', 'events', 'schedule'])
  })

  it('job 块出 needs / if / steps', () => {
    expect(labels(optionsAt('jobs:\n  体检:\n    nee|'))).toEqual(['needs', 'if', 'steps'])
  })

  it('step 块出 uses / with / severity / continue-on-error', () => {
    const doc = `${JOB_DOC}\n        se|`
    expect(labels(optionsAt(doc))).toEqual(['uses', 'with', 'severity', 'continue-on-error'])
  })

  it('severity 值位只出三档严重度', () => {
    const doc = `${JOB_DOC}\n        severity: er|`
    expect(labels(optionsAt(doc))).toEqual(['error', 'warn', 'info'])
  })
})

describe('pipelineCompletion 规则引用与片段（C5 / C7）', () => {
  it('uses 值位补全检查动作目录（detail 含标题与类别）', () => {
    const result = optionsAt('jobs:\n  体检:\n    steps:\n      - uses: table/nu|')
    expect(labels(result)).toEqual(['table/null-rate', 'document/broken-refs'])
    expect(result!.options[0]!.detail).toBe('空值比例 · 数据表')
  })

  it('uses 值位目录为空时静默无候选', () => {
    expect(optionsAt('jobs:\n  体检:\n    steps:\n      - uses: ta|', { checks: [] })).toBeNull()
  })

  it('with 键位补全该 uses 的 inputs（detail = 类型 + 描述 + 默认值）', () => {
    const doc = `${JOB_DOC}\n          tab|`
    const result = optionsAt(doc)
    expect(labels(result)).toEqual(['table', 'fields', 'max_rate'])
    expect(result!.options[0]!.detail).toBe('string · 目标表')
    expect(result!.options[2]!.detail).toBe('number · 允许空值率 · 默认 0.2')
  })

  it('with 键位对应动作无 inputs 时无候选', () => {
    const doc = 'jobs:\n  体检:\n    steps:\n      - uses: document/broken-refs\n        with:\n          br|'
    expect(optionsAt(doc)).toBeNull()
  })

  it('steps 块给出检查动作的步骤骨架片段', () => {
    const doc = 'jobs:\n  体检:\n    steps:\n      - '
    const result = optionsAt(doc)
    expect(labels(result)).toEqual(['空值比例 步骤', '引用完整性 步骤'])
    expect(result!.options[0]!.detail).toBe('table/null-rate')
    expect(typeof result!.options[0]!.apply).toBe('function')
  })
})

describe('pipelineCompletion 内置动作参数值提示（C12）', () => {
  const SENSITIVE = [
    'jobs:',
    '  体检:',
    '    steps:',
    '      - uses: document/sensitive',
    '        with:',
    '          rules:',
    '            - name: 手机号',
    "              patterns: ['\\b1\\d{10}\\b']",
    '            - name: 白名单',
    '              keywords: [公开联系人]',
  ].join('\n')

  it('logic 值位提示 any / all 与 rules 里已定义的规则名', () => {
    const doc = `${SENSITIVE}\n          logic: |`
    const result = optionsAt(doc)
    expect(labels(result)).toEqual(['any', 'all', '手机号', '白名单'])
    expect(result!.options[2]!.detail).toBe('敏感规则名')
  })

  it('logic 布尔表达式中继续提示规则名', () => {
    const doc = `${SENSITIVE}\n          logic: 手机号 and 白|`
    expect(labels(optionsAt(doc))).toEqual(['any', 'all', '手机号', '白名单'])
  })

  it('顶层 keywords / patterns 会提示隐式规则 default', () => {
    const doc = [
      'jobs:',
      '  体检:',
      '    steps:',
      '      - uses: document/sensitive',
      '        with:',
      '          keywords: [内部资料]',
      '          logic: |',
    ].join('\n')
    expect(labels(optionsAt(doc))).toEqual(['any', 'all', 'default'])
  })

  it('rules 列表项键位提示 name / keywords / patterns', () => {
    const doc = `${SENSITIVE}\n          logic: any\n          rules:\n            - |`
    expect(labels(optionsAt(doc))).toEqual(['name', 'keywords', 'patterns'])
  })

  it('非敏感动作不提供 logic / rules 值级提示', () => {
    const doc = [
      'jobs:',
      '  体检:',
      '    steps:',
      '      - uses: table/null-rate',
      '        with:',
      '          rules:',
      '            - |',
    ].join('\n')
    expect(optionsAt(doc)).toBeNull()
    const logicDoc = [
      'jobs:',
      '  体检:',
      '    steps:',
      '      - uses: table/null-rate',
      '        with:',
      '          logic: |',
    ].join('\n')
    expect(optionsAt(logicDoc)).toBeNull()
  })
})

describe('pipelineCompletion 本地引用（C6）', () => {
  const MULTI_JOB = [
    'jobs:',
    '  体检:',
    '    steps:',
    '      - uses: table/null-rate',
    '  汇总:',
    '    needs: 体|',
  ].join('\n')

  it('needs 值位补全其他 job id（排除自身）', () => {
    expect(labels(optionsAt(MULTI_JOB))).toEqual(['体检'])
  })

  it('needs 流式列表内按逗号分段补全', () => {
    const doc = 'jobs:\n  体检:\n    steps:\n      - uses: table/null-rate\n  汇总:\n    needs: [体检, |'
    expect(labels(optionsAt(doc, {}, true))).toEqual(['体检'])
  })

  it('表达式位补全 vars 变量名', () => {
    const doc = 'vars:\n  threshold: 10\njobs:\n  体检:\n    if: ${{ thr| }}\n    steps:\n      - uses: table/null-rate'
    expect(labels(optionsAt(doc))).toEqual(['vars.threshold'])
  })

  it('with 值位的表达式同样补全变量名', () => {
    const doc = `vars:\n  threshold: 10\n${JOB_DOC}\n          max_rate: \${{ thr| }}`
    expect(labels(optionsAt(doc))).toEqual(['vars.threshold'])
  })

  it('无 vars 定义时不返回候选', () => {
    const doc = `${JOB_DOC}\n        if: \${{ thr| }}`
    expect(optionsAt(doc)).toBeNull()
  })

  it('行级扫描忽略注释与嵌套键，job 缩进取 jobs 块首层', () => {
    const doc = [
      'vars:',
      '  threshold: 1',
      '  # ignored: 1',
      'jobs:',
      '  # 体检:',
      '  体检:',
      '    steps:',
      '      - uses: table/null-rate',
      '  汇总:',
      '    needs: 体检',
    ].join('\n')
    expect(extractPipelineSymbols(doc)).toEqual({
      vars: ['threshold'],
      jobIds: ['体检', '汇总'],
      jobIndent: 2,
    })
    expect(currentJobId(doc, doc.indexOf('needs'))).toBe('汇总')
  })
})

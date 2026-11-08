/** 结构 DSL 自动完成（需求卡 0110 P0-P2）.
 *
 * 选型：CodeMirror 官方 `@codemirror/autocomplete`（`autocompletion` + `snippet`），
 * 不自研补全框架、不新增后端端点。上下文判定是轻量文本规则（不做前端解析器），
 * 扫描误差不阻断输入，语法正确性仍由后端编译诊断兜底。
 *
 * 单一语法口径：关键字 / 图元 / 约束类型 / 锚点 / 白名单函数全部来自 `designLang`
 * 导出的常量（与后端 `services/dsl/parse.py` 逐项对齐）；片段形参与 `compile.py`
 * 的 `_eval_*` 一致。
 */

import { snippet, type Completion, type CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import {
  BOOLEANS,
  CONSTRAINT_ANCHORS,
  CONSTRAINT_TYPES,
  CONSTANTS,
  FUNCTIONS,
  PRIMITIVES,
  STATEMENT_KEYWORDS,
  TRANSFORMS,
} from './designLang'

/** 跨文件零件候选（由宿主页注入，`use "` 字符串位使用） */
export interface DslPartOption {
  label: string
  detail?: string
}

/** 轻量扫描得到的文档内符号 */
export interface DslSymbols {
  /** 顶层 `param` 名 */
  params: string[]
  /** `module` 名与形参表 */
  modules: Array<{ name: string; params: string[] }>
  /** `use ... as 标签` */
  labels: string[]
}

/** 复用模块候选（ADR 0118 P1，`use "lib:` 字符串位使用） */
export interface DslLibraryOption {
  moduleKey: string
  name: string
  latestVersion: number
}

/** 补全源可选依赖：零件名获取函数（P2；缺省时字符串位不出候选） */
export interface DslCompletionOptions {
  fetchParts?: () => Promise<readonly DslPartOption[]>
  /** 复用模块库候选（P1；缺省时 `lib:` 位不出候选） */
  fetchLibrary?: () => Promise<readonly DslLibraryOption[]>
}

/** 图元命名参数（与 `_eval_*` 的 allowed 集合一致）与一句话说明 */
export const PRIMITIVE_SIGNATURES: Record<string, { params: string[]; detail: string }> = {
  box: { params: ['size', 'w', 'h', 'd'], detail: 'size=[x,y,z] 或 w/h/d' },
  cyl: { params: ['d', 'h', 'fn'], detail: '直径 d / 高 h（fn 为分段数）' },
  sphere: { params: ['r', 'fn'], detail: '半径 r（fn 为分段数）' },
  cone: { params: ['d1', 'd2', 'h', 'fn'], detail: '两端直径 d1 / d2 与高 h' },
  torus: { params: ['r', 'tube', 'fn'], detail: '中心半径 r / 管径 tube' },
  tube: { params: ['od', 'id', 'h', 'fn'], detail: '外径 od / 内径 id / 高 h' },
}

/** 关键字说明（补全 detail 的中文一句话） */
const KEYWORD_DETAILS: Record<string, string> = {
  param: '顶层参数声明',
  module: '组件模块声明',
  system: '系统装配声明',
  use: '引用其他设计文件',
  as: '实例标签',
  constraint: '装配约束声明',
  union: '布尔组合：并集',
  difference: '布尔组合：差集',
  intersection: '布尔组合：交集',
  translate: '变换：平移',
  rotate: '变换：旋转',
  scale: '变换：缩放',
  mirror: '变换：镜像',
  fixed: '约束类型：固定',
  coincident: '约束类型：重合',
  concentric: '约束类型：同轴',
  distance: '约束类型：距离',
  angle: '约束类型：角度',
}

/** 关键字全集（C1：与后端语法面逐项一致，供单测硬编码比对） */
export const DSL_KEYWORDS: string[] = [
  ...STATEMENT_KEYWORDS,
  ...BOOLEANS,
  ...TRANSFORMS,
  ...CONSTRAINT_TYPES,
]

/** 片段模板（C4）：`$` 槽位由 CodeMirror `snippet()` 展开，Tab 跳转 */
export const DSL_SNIPPET_TEMPLATES: Record<string, string> = {
  param: 'param ${name} = ${1:1}',
  module: 'module ${name}(${1:a}) {\n  ${2:box(size = [10, 10, 10])}\n}',
  system: 'system ${name} {\n  ${1:box(size = [10, 10, 10])}\n}',
  use: 'use "${1:file_key}"(${2}) as ${3:label}',
  constraint: 'constraint ${1:c1} ${2:fixed}(a = ${3:label.origin})',
  box: 'box(size = [${1:10}, ${2:10}, ${3:10}])',
  cyl: 'cyl(d = ${1:10}, h = ${2:10})',
  sphere: 'sphere(r = ${1:5})',
  cone: 'cone(d1 = ${1:10}, d2 = ${2:5}, h = ${3:10})',
  torus: 'torus(r = ${1:10}, tube = ${2:2})',
  tube: 'tube(od = ${1:10}, id = ${2:6}, h = ${3:10})',
  union: 'union {\n  ${1:box(size = [10, 10, 10])}\n  ${2:cyl(d = 6, h = 10)}\n}',
  difference: 'difference {\n  ${1:box(size = [10, 10, 10])}\n  ${2:cyl(d = 6, h = 10)}\n}',
  intersection: 'intersection {\n  ${1:box(size = [10, 10, 10])}\n  ${2:sphere(r = 4)}\n}',
  translate: 'translate([${1:0}, ${2:0}, ${3:0}]) ${4:box(size = [10, 10, 10])}',
  rotate: 'rotate([${1:0}, ${2:0}, ${3:0}]) ${4:box(size = [10, 10, 10])}',
  scale: 'scale([${1:1}, ${2:1}, ${3:1}]) ${4:box(size = [10, 10, 10])}',
  mirror: 'mirror([${1:1}, ${2:0}, ${3:0}]) ${4:box(size = [10, 10, 10])}',
}

/** 片段补全项（label 用中文说明，避免与关键字候选重名） */
export const dslSnippets: Completion[] = Object.entries(DSL_SNIPPET_TEMPLATES).map(([name, template]) => ({
  label: `${name} 片段`,
  type: 'snippet',
  detail: KEYWORD_DETAILS[name] ?? `${name} 模板`,
  apply: snippet(template),
}))

/** 去掉注释与字符串内容（等长替换为空格，保留换行；轻量扫描与上下文判定共用） */
export function stripCommentsAndStrings(doc: string): string {
  const out: string[] = []
  let state: 'code' | 'line' | 'block' | 'string' = 'code'
  for (let i = 0; i < doc.length; i += 1) {
    const ch = doc[i]
    const next = doc[i + 1]
    if (state === 'code') {
      if (ch === '/' && next === '/') {
        state = 'line'
        out.push(' ', ' ')
        i += 1
      } else if (ch === '/' && next === '*') {
        state = 'block'
        out.push(' ', ' ')
        i += 1
      } else if (ch === '"') {
        state = 'string'
        out.push(' ')
      } else {
        out.push(ch)
      }
      continue
    }
    if (state === 'line') {
      if (ch === '\n') {
        state = 'code'
        out.push('\n')
      } else {
        out.push(' ')
      }
      continue
    }
    if (state === 'block') {
      if (ch === '*' && next === '/') {
        state = 'code'
        out.push(' ', ' ')
        i += 1
      } else {
        out.push(ch === '\n' ? '\n' : ' ')
      }
      continue
    }
    // string
    if (ch === '"') {
      state = 'code'
      out.push(' ')
    } else {
      out.push(ch === '\n' ? '\n' : ' ')
    }
  }
  return out.join('')
}

/** 解析形参表（`d` / `d = 10` 混合；忽略非法名字） */
function splitParams(raw: string): string[] {
  return raw
    .split(',')
    .map(item => item.trim().split('=')[0]!.trim())
    .filter(name => /^[A-Za-z_][A-Za-z0-9_]*$/.test(name))
}

/** 从当前文档提取可补全符号（C2）：param 名 / module 名与形参 / use as 标签 */
export function extractSymbols(doc: string): DslSymbols {
  const params = new Set<string>()
  const labels = new Set<string>()
  const modules = new Map<string, string[]>()
  for (const line of stripCommentsAndStrings(doc).split('\n')) {
    const paramMatch = /^\s*param\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(line)
    if (paramMatch?.[1]) params.add(paramMatch[1])
    const moduleMatch = /^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)/.exec(line)
    if (moduleMatch?.[1]) modules.set(moduleMatch[1], splitParams(moduleMatch[2]!))
    const labelMatch = /\buse\b[^\n]*?\bas\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(line)
    if (labelMatch?.[1]) labels.add(labelMatch[1])
  }
  return {
    params: [...params],
    modules: [...modules].map(([name, names]) => ({ name, params: names })),
    labels: [...labels],
  }
}

/** 从 `{` 起找匹配的 `}`（已剥离字符串 / 注释） */
function matchBrace(strippedDoc: string, open: number): number {
  let depth = 0
  for (let i = open; i < strippedDoc.length; i += 1) {
    if (strippedDoc[i] === '{') depth += 1
    else if (strippedDoc[i] === '}') {
      depth -= 1
      if (depth === 0) return i
    }
  }
  return -1
}

/** 光标所在 module 块的形参（0127 C6）：嵌套布尔块不影响作用域，不在模块体内返回空 */
export function enclosingModuleParams(strippedDoc: string, pos: number): string[] {
  const pattern = /\bmodule\s+[A-Za-z_][A-Za-z0-9_]*\s*\(([^)]*)\)\s*\{/g
  let bestOpen = -1
  let bestParams: string[] = []
  for (let match = pattern.exec(strippedDoc); match; match = pattern.exec(strippedDoc)) {
    const open = match.index + match[0].length - 1
    if (open >= pos) continue
    const close = matchBrace(strippedDoc, open)
    if (close === -1 || pos > close) continue
    // 取最内层模块（嵌套场景以开块位置最大者为准）
    if (open > bestOpen) {
      bestOpen = open
      bestParams = splitParams(match[1] ?? '')
    }
  }
  return bestParams
}

/** 光标所在最近一层 `(` 的调用名（跳过字符串 / 注释；向量内返回 null） */
export function findCallContext(strippedDoc: string, pos: number): string | null {
  let parenDepth = 0
  let bracketDepth = 0
  for (let i = pos - 1; i >= 0; i -= 1) {
    const ch = strippedDoc[i]
    if (ch === ')') parenDepth += 1
    else if (ch === '(') {
      if (parenDepth === 0) {
        const name = /([A-Za-z_][A-Za-z0-9_]*)\s*$/.exec(strippedDoc.slice(Math.max(0, i - 64), i))?.[1]
        return name ?? null
      }
      parenDepth -= 1
    } else if (ch === ']') bracketDepth += 1
    else if (ch === '[') {
      if (bracketDepth === 0) return null
      bracketDepth -= 1
    } else if (ch === '{' || ch === '}') {
      return null
    }
  }
  return null
}

function keywordOptions(): Completion[] {
  return DSL_KEYWORDS.map(label => ({ label, type: 'keyword', detail: KEYWORD_DETAILS[label] ?? label }))
}

/** 约束类型候选（0127 C9） */
function constraintTypeOptions(): Completion[] {
  return CONSTRAINT_TYPES.map(label => ({
    label,
    type: 'keyword',
    detail: KEYWORD_DETAILS[label] ?? '约束类型',
  }))
}

/** 候选去重（0127 C10）：保留首次出现，本地符号由调用方排在前面 */
function dedupeOptions(options: Completion[]): Completion[] {
  const seen = new Set<string>()
  return options.filter(option => {
    if (seen.has(option.label)) return false
    seen.add(option.label)
    return true
  })
}

/** 候选包装：统一去重 */
function result(from: number, options: Completion[]): CompletionResult {
  return { from, options: dedupeOptions(options) }
}

/** 表达式位候选（0127 C6）：模块形参优先，其次顶层 param / 常量 / 函数 */
function expressionOptions(symbols: DslSymbols, localParams: string[] = []): Completion[] {
  return dedupeOptions([
    ...localParams.map(label => ({ label, type: 'variable', detail: '模块形参' })),
    ...symbols.params.map(label => ({ label, type: 'variable', detail: '参数' })),
    ...CONSTANTS.map(label => ({ label, type: 'constant', detail: '常量' })),
    ...FUNCTIONS.map(label => ({ label, type: 'function', detail: '白名单函数' })),
  ])
}

/** 实例位候选（0127 C8）：图元 / 模块名 / 实例类片段，不出语句关键字 */
const INSTANCE_SNIPPET_NAMES = new Set<string>([
  ...PRIMITIVES, ...BOOLEANS, ...TRANSFORMS,
])

function instanceOptions(symbols: DslSymbols): Completion[] {
  return dedupeOptions([
    ...PRIMITIVES.map(label => ({
      label,
      type: 'type',
      detail: PRIMITIVE_SIGNATURES[label]?.detail ?? '图元',
    })),
    ...symbols.modules.map(module => ({ label: module.name, type: 'class', detail: '模块调用' })),
    ...dslSnippets.filter(item => INSTANCE_SNIPPET_NAMES.has(item.label.replace(' 片段', ''))),
  ])
}

function statementOptions(symbols: DslSymbols): Completion[] {
  return dedupeOptions([
    ...keywordOptions(),
    ...symbols.modules.map(module => ({ label: module.name, type: 'class', detail: '模块调用' })),
    ...dslSnippets,
  ])
}

/** 自动完成源（C1-C5 / C10）：按光标上下文分流候选 */
export async function dslCompletionSource(
  context: CompletionContext,
  options: DslCompletionOptions = {},
): Promise<CompletionResult | null> {
  const { state, pos } = context
  const doc = state.doc.toString()
  const line = state.doc.lineAt(pos)
  const before = line.text.slice(0, pos - line.from)

  // P2：`use "` 字符串位 → 跨文件零件名（异步，失败静默降级为空候选）
  const useString = /(?:^|[\s;(])use\s+"([^"]*)$/.exec(before)
  if (useString) {
    const typed = useString[1]!
    const from = line.from + before.length - typed.length
    // P1：`lib:` 位 → 模块 key 与最新版本（ADR 0118）
    if (typed.startsWith('lib:')) {
      if (!options.fetchLibrary) return null
      let modules: readonly DslLibraryOption[] = []
      try {
        modules = await options.fetchLibrary()
      } catch {
        modules = []
      }
      if (modules.length === 0) return null
      const versionMatch = /^lib:([^@"]*)@([0-9]*)$/.exec(typed)
      if (versionMatch) {
        const hit = modules.find(module => module.moduleKey === versionMatch[1])
        const versionText = versionMatch[2]!
        return {
          from: pos - versionText.length,
          options: hit
            ? [{
                label: String(hit.latestVersion),
                type: 'constant',
                detail: `最新版本 v${hit.latestVersion}`,
              }]
            : [],
          validFor: /^[0-9]*$/,
        }
      }
      const keyMatch = /^lib:([^@"]*)$/.exec(typed)
      const prefix = (keyMatch?.[1] ?? '').toLowerCase()
      const matched = modules.filter(module => (
        !prefix || module.moduleKey.toLowerCase().includes(prefix) || module.name.toLowerCase().includes(prefix)
      ))
      if (matched.length === 0) return null
      return {
        from,
        options: matched.map(module => ({
          label: `lib:${module.moduleKey}@${module.latestVersion}`,
          type: 'text',
          detail: `${module.name} · v${module.latestVersion}`,
        })),
        validFor: /^lib:[^"]*$/,
      }
    }
    if (!options.fetchParts) return null
    let parts: readonly DslPartOption[] = []
    try {
      parts = await options.fetchParts()
    } catch {
      parts = []
    }
    if (parts.length === 0) return null
    return {
      from,
      options: parts.map(part => ({ label: part.label, type: 'text', detail: part.detail ?? '设计文件' })),
      validFor: /^[^"]*$/,
    }
  }

  const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_]*/)
  // 标识符输入自动触发；无输入时仅 Ctrl+Space 手动唤起
  if (!word && !context.explicit) return null
  const from = word ? word.from : pos
  const symbols = extractSymbols(doc)
  const strippedDoc = stripCommentsAndStrings(doc)
  const localParams = enclosingModuleParams(strippedDoc, pos)

  // 约束行（0127 C9）：锚点位 / 类型位 / 参数位 / 类型未定
  if (/^\s*constraint\b/.test(before)) {
    if (/[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_]*$/.test(before)) {
      return result(from, CONSTRAINT_ANCHORS.map(label => ({ label, type: 'atom', detail: '约束锚点' })))
    }
    if (/^\s*constraint\s+[A-Za-z_][A-Za-z0-9_]*\s+[A-Za-z0-9_]*$/.test(before)) {
      return result(from, constraintTypeOptions())
    }
    if (/^\s*constraint\b[^\n]*\([^)]*$/.test(before)) {
      return result(from, [
        ...symbols.labels.map(label => ({ label, type: 'variable', detail: '实例标签' })),
        ...CONSTRAINT_ANCHORS.map(label => ({ label, type: 'atom', detail: '约束锚点' })),
        ...expressionOptions(symbols, localParams),
      ])
    }
    return result(from, [
      ...constraintTypeOptions(),
      ...symbols.labels.map(label => ({ label, type: 'variable', detail: '实例标签' })),
      ...CONSTRAINT_ANCHORS.map(label => ({ label, type: 'atom', detail: '约束锚点' })),
    ])
  }

  const prev = before.trimEnd().slice(-1)
  // 表达式位：`=` 之后或运算符之后
  if (prev === '=' || '+-*/%'.includes(prev)) {
    return result(from, expressionOptions(symbols, localParams))
  }

  // 变换后的内联实例位（0127 C8）：出图元 / 模块 / 实例片段
  if (/(?:^|\s)(?:translate|rotate|scale|mirror)\s*\(.*\)\s+[A-Za-z_][A-Za-z0-9_]*$/.test(before.trim())) {
    return result(from, instanceOptions(symbols))
  }

  // 调用括号内：模块命名实参 / 图元命名参数
  const callName = findCallContext(strippedDoc, pos)
  if (callName) {
    const module = symbols.modules.find(item => item.name === callName)
    if (module) {
      return result(from, module.params.map(label => ({
        label,
        type: 'property',
        detail: `${module.name} 形参`,
        apply: `${label} = `,
      })))
    }
    const signature = PRIMITIVE_SIGNATURES[callName]
    if (signature) {
      return result(from, signature.params.map(label => ({ label, type: 'property', detail: signature.detail })))
    }
  }

  // 行首 / 块内实例位：语句关键字 + 模块名 + 骨架片段
  if (/^\s*[A-Za-z_][A-Za-z0-9_]*$/.test(before)) {
    return result(from, statementOptions(symbols))
  }

  return result(from, expressionOptions(symbols, localParams))
}

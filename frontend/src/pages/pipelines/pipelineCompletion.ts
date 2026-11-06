/** 流水线检查 DSL 自动完成（需求卡 0111 P0-P2，C4-C7）.
 *
 * 选型：CodeMirror 官方 `@codemirror/autocomplete`（与需求 0110 共用依赖），
 * 不自研补全框架、不新增后端端点。上下文判定是轻量行级文本规则（不做完整前端
 * 解析器），扫描误差不阻断输入，语法正确性仍由既有 400ms 防抖 `/validate` 兜底。
 *
 * 单一语法口径：关键字 / 严重度全部来自 `pipelineDsl` 导出的常量（与后端
 * `services/dsl/parse.py` 逐项对齐）；片段生成复用 `checkCatalog` 的
 * `buildStepSnippet` / `defaultWorkflowContent`，与目录「插入」按钮同源。
 */

import { snippet, type Completion, type CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import { buildStepSnippet, CHECK_CATEGORY_LABEL, defaultWorkflowContent } from './checkCatalog'
import {
  JOB_KEYWORDS,
  KEYWORD_DETAILS,
  ON_KEYWORDS,
  SEVERITIES,
  STEP_KEYWORDS,
  TOP_KEYWORDS,
} from './pipelineDsl'

/** 检查动作输入（结构对齐 `PipelineCheckInput`，避免补全模块依赖 api 层，C5） */
export interface PipelineCheckInputLike {
  name: string
  type: string
  description: string
  required: boolean
  default: unknown
}

/** 检查动作目录项（由 `PipelinesPage` 经 props 注入，C5） */
export interface PipelineCheckLike {
  uses: string
  title: string
  category: string
  severity: 'error' | 'warn' | 'info'
  target_types: string[]
  inputs: PipelineCheckInputLike[]
}

/** 补全选项：目录数据与域模板（均由宿主页注入） */
export interface PipelineCompletionOptions {
  checks?: readonly PipelineCheckLike[]
  domain?: 'table' | 'document'
}

/** 轻量扫描得到的文档内符号（C6） */
export interface PipelineSymbols {
  /** `vars:` 下的变量名 */
  vars: string[]
  /** `jobs:` 下的作业 id */
  jobIds: string[]
  /** jobs 块的作业缩进（无 jobs 块为 null） */
  jobIndent: number | null
}

/** 去掉行内注释（保留引号内的 `#`） */
function stripLineComment(line: string): string {
  let quote: string | null = null
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (quote) {
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") {
      quote = ch
      continue
    }
    if (ch === '#') return line.slice(0, i)
  }
  return line
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length
}

/** 行级扫描：`vars` 变量名与 `jobs` 作业 id（C6，误差不阻断输入） */
export function extractPipelineSymbols(doc: string): PipelineSymbols {
  const vars: string[] = []
  const jobIds: string[] = []
  let varIndent: number | null = null
  let jobIndent: number | null = null
  let inVars = false
  let inJobs = false
  for (const raw of doc.split('\n')) {
    const line = stripLineComment(raw)
    if (!line.trim()) continue
    const indent = indentOf(line)
    const trimmed = line.trim()
    if (indent === 0) {
      inVars = trimmed === 'vars:'
      inJobs = trimmed === 'jobs:'
      varIndent = null
      jobIndent = null
      continue
    }
    if (inVars) {
      if (varIndent === null) varIndent = indent
      if (indent === varIndent) {
        const match = /^([A-Za-z_][A-Za-z0-9_]*):/.exec(trimmed)
        if (match?.[1]) vars.push(match[1])
      }
      continue
    }
    if (inJobs && !trimmed.startsWith('-')) {
      const match = /^([^\s:#][^:#]*?):\s*(?:#.*)?$/.exec(trimmed)
      if (match?.[1]) {
        if (jobIndent === null) jobIndent = indent
        if (indent === jobIndent) jobIds.push(match[1].trim())
      }
    }
  }
  return { vars, jobIds, jobIndent }
}

/** 光标所在 job id（`needs:` 补全时排除自身，C6） */
export function currentJobId(doc: string, pos: number): string | null {
  const { jobIndent } = extractPipelineSymbols(doc)
  if (jobIndent === null) return null
  const lines = doc.split('\n').map(stripLineComment)
  const cursorLine = doc.slice(0, pos).split('\n').length - 1
  for (let i = Math.min(cursorLine, lines.length - 1); i >= 0; i -= 1) {
    const line = lines[i]!
    if (!line.trim()) continue
    const indent = indentOf(line)
    if (indent < jobIndent) return null
    if (indent === jobIndent) {
      const match = /^\s*([^\s:#][^:#]*?):\s*(?:#.*)?$/.exec(line)
      if (match?.[1]) return match[1].trim()
    }
  }
  return null
}

/** 光标上方最近一层缩进更浅的键（上下文分流的基础） */
interface ParentKey {
  key: string
  index: number
}

function parentKeyAbove(lines: string[], lineIndex: number, indent: number): ParentKey | null {
  for (let i = lineIndex - 1; i >= 0; i -= 1) {
    const line = lines[i]!
    if (!line.trim()) continue
    if (indentOf(line) >= indent) continue
    const trimmed = line.trim().replace(/^-\s+/, '')
    const match = /^([^\s:#][^:#]*?):/.exec(trimmed)
    return { key: match?.[1]?.trim() ?? '', index: i }
  }
  return null
}

/** 从 `with:` 行向上找对应的 `uses` 值（C5） */
function findUsesAbove(lines: string[], fromIndex: number): string | null {
  for (let i = fromIndex; i >= 0; i -= 1) {
    const match = /(?:^|\s)uses:\s*([^\s#]+)/.exec(lines[i]!)
    if (match?.[1]) return match[1]
  }
  return null
}

/** 值级提示的目标动作（C12；新增动作在此登记值提示口径） */
const SENSITIVE_USES = 'document/sensitive'

/** `document/sensitive` 的 `logic` 固定取值（C12） */
const SENSITIVE_LOGIC_PRESETS = [
  { label: 'any', detail: '任一规则命中' },
  { label: 'all', detail: '全部规则命中' },
] as const

/** `document/sensitive` 命名规则项允许的键（与后端 `_RULE_KEYS` 对齐，C12） */
const SENSITIVE_RULE_KEYS = [
  { label: 'name', detail: '规则名（logic 中按字面引用）' },
  { label: 'keywords', detail: '关键词列表（任一命中算该规则命中）' },
  { label: 'patterns', detail: '正则表达式列表（任一命中算该规则命中）' },
] as const

/** `with` 块的直接子键行（如 `rules:`），找不到返回 null */
function findChildKeyLine(lines: string[], withIndex: number, key: string): number | null {
  const base = indentOf(lines[withIndex]!)
  let childIndent: number | null = null
  for (let i = withIndex + 1; i < lines.length; i += 1) {
    const line = lines[i]!
    if (!line.trim()) continue
    const indent = indentOf(line)
    if (indent <= base) return null
    if (childIndent === null) childIndent = indent
    if (indent === childIndent && new RegExp(`^\\s*${key}:`).test(line)) return i
  }
  return null
}

/** 去掉 YAML 标量两侧引号 */
function unquote(text: string): string {
  return text.trim().replace(/^['"]|['"]$/g, '').trim()
}

/** 从 `rules` 值提取命名规则（块式 / 单行流式都尽量识别，C12） */
function extractSensitiveRuleNames(lines: string[], rulesIndex: number): string[] {
  const names: string[] = []
  const seen = new Set<string>()
  const push = (raw: string) => {
    const name = unquote(raw)
    if (name && !seen.has(name)) {
      seen.add(name)
      names.push(name)
    }
  }
  const rulesLine = lines[rulesIndex]!
  const inline = rulesLine.replace(/^\s*rules:\s*/, '')
  if (inline) {
    for (const match of inline.matchAll(/name:\s*("[^"]*"|'[^']*'|[^,}\]\s][^,}\]\n]*)/g)) {
      if (match[1]) push(match[1])
    }
  }
  const base = indentOf(rulesLine)
  for (let i = rulesIndex + 1; i < lines.length; i += 1) {
    const line = lines[i]!
    if (!line.trim()) continue
    if (indentOf(line) <= base) break
    const match = /^\s*(?:-\s*)?name:\s*(.+)$/.exec(line)
    if (match?.[1]) push(match[1])
  }
  return names
}

/** `with` 块顶层是否写了 `keywords` / `patterns`（会合并为隐式规则 `default`） */
function hasImplicitDefaultRule(lines: string[], withIndex: number): boolean {
  const base = indentOf(lines[withIndex]!)
  let childIndent: number | null = null
  for (let i = withIndex + 1; i < lines.length; i += 1) {
    const line = lines[i]!
    if (!line.trim()) continue
    const indent = indentOf(line)
    if (indent <= base) break
    if (childIndent === null) childIndent = indent
    if (indent !== childIndent) continue
    const match = /^(?:keywords|patterns):\s*(.*)$/.exec(line.trim())
    if (!match) continue
    if (match[1]) return true
    // 空值后跟列表项同样算写了顶层关键词 / 正则
    for (let j = i + 1; j < lines.length; j += 1) {
      const next = lines[j]!
      if (!next.trim()) continue
      if (indentOf(next) <= childIndent) break
      if (/^\s*-/.test(next)) return true
      break
    }
  }
  return false
}

/** 是否位于未闭合的 `${{ ... }}` 表达式内（C6） */
function inExpression(before: string): boolean {
  const open = before.lastIndexOf('${{')
  if (open === -1) return false
  return before.lastIndexOf('}}') < open
}

function keywordOptions(list: readonly string[]): Completion[] {
  return list.map(label => ({
    label,
    type: 'keyword',
    detail: KEYWORD_DETAILS[label] ?? label,
  }))
}

function inputDetail(input: PipelineCheckInputLike): string {
  const parts = [input.type]
  if (input.description) parts.push(input.description)
  if (input.default !== null && input.default !== undefined) {
    const value = Array.isArray(input.default) ? `[${input.default.join(', ')}]` : String(input.default)
    parts.push(`默认 ${value}`)
  }
  return parts.join(' · ')
}

function checkLabel(check: PipelineCheckLike): string {
  const category = CHECK_CATEGORY_LABEL[check.category] ?? check.category
  return `${check.title} · ${category}`
}

/** 自动完成源（C4-C7）：按光标上下文分流候选 */
export function pipelineCompletionSource(
  context: CompletionContext,
  options: PipelineCompletionOptions = {},
): CompletionResult | null {
  const { state, pos } = context
  const doc = state.doc.toString()
  const line = state.doc.lineAt(pos)
  const before = stripLineComment(line.text.slice(0, pos - line.from))
  const checks = options.checks ?? []
  const lines = doc.split('\n').map(stripLineComment)
  const lineIndex = line.number - 1

  // C5：`uses:` 值位 → 检查动作目录
  const usesValue = /(?:^|\s)uses:\s*([^\s#]*)$/.exec(before)
  if (usesValue) {
    const typed = usesValue[1] ?? ''
    if (checks.length === 0) return null
    return {
      from: pos - typed.length,
      options: checks.map(check => ({
        label: check.uses,
        type: 'text',
        detail: checkLabel(check),
      })),
      validFor: /^[^\s#]*$/,
    }
  }

  // C4：`severity:` 值位 → error / warn / info
  const severityValue = /(?:^|\s)severity:\s*([\w-]*)$/.exec(before)
  if (severityValue) {
    const typed = severityValue[1] ?? ''
    return {
      from: pos - typed.length,
      options: keywordOptions(SEVERITIES),
      validFor: /^[\w-]*$/,
    }
  }

  // C6：`needs:` 值位 → 当前文档其他 job id
  const needsValue = /(?:^|\s)needs:\s*\[?([^\]\n]*)$/.exec(before)
  if (needsValue) {
    const inner = needsValue[1] ?? ''
    const typed = inner.slice(inner.lastIndexOf(',') + 1).trimStart()
    const current = currentJobId(doc, pos)
    const { jobIds } = extractPipelineSymbols(doc)
    const candidates = jobIds.filter(id => id !== current)
    if (candidates.length === 0) return null
    return {
      from: pos - typed.length,
      options: candidates.map(label => ({ label, type: 'variable', detail: '作业 id' })),
      validFor: /^[\w\u4e00-\u9fff-]*$/,
    }
  }

  const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_.-]*/)
  const from = word ? word.from : pos

  // C6：表达式位 / `if:` 值位 / `vars` 值位 → 变量名（`vars.<name>`）
  const indent = indentOf(before)
  const parent = parentKeyAbove(lines, lineIndex, indent)
  const varsValue = parent?.key === 'vars' && !/^\s*[\w-]*$/.test(before)
  if (inExpression(before) || /(?:^|\s)if:\s*[^#]*$/.test(before) || varsValue) {
    const { vars } = extractPipelineSymbols(doc)
    if (vars.length === 0) return null
    const expressionWord = context.matchBefore(/[A-Za-z_][A-Za-z0-9_.]*/)
    return {
      from: expressionWord ? expressionWord.from : pos,
      options: vars.map(name => ({
        label: `vars.${name}`,
        type: 'variable',
        detail: '流水线变量',
      })),
      validFor: /^[A-Za-z0-9_.]*$/,
    }
  }

  // C12：`document/sensitive` 的 `logic` 值位 → any / all / 已定义规则名
  const sensitiveLogic = /(?:^|\s)logic:\s*([^\n#]*)$/.exec(before)
  if (sensitiveLogic && parent?.key === 'with'
    && findUsesAbove(lines, parent.index) === SENSITIVE_USES) {
    const typed = /[^\s()&|!]*$/.exec(sensitiveLogic[1] ?? '')?.[0] ?? ''
    const rulesIndex = findChildKeyLine(lines, parent.index, 'rules')
    const ruleNames = rulesIndex === null ? [] : extractSensitiveRuleNames(lines, rulesIndex)
    if (hasImplicitDefaultRule(lines, parent.index)) ruleNames.unshift('default')
    return {
      from: pos - typed.length,
      options: [
        ...SENSITIVE_LOGIC_PRESETS.map(item => ({ label: item.label, type: 'keyword' as const, detail: item.detail })),
        ...ruleNames.map(name => ({ label: name, type: 'variable' as const, detail: '敏感规则名' })),
      ],
      validFor: /^[^\s()&|!]*$/,
    }
  }

  // C12：`document/sensitive` 的 `rules` 列表项键位 → name / keywords / patterns
  if (parent?.key === 'rules'
    && /^\s*-\s*[\w-]*$|^\s*[\w-]*$/.test(before)
    && findUsesAbove(lines, parent.index) === SENSITIVE_USES) {
    return {
      from,
      options: SENSITIVE_RULE_KEYS.map(item => ({ label: item.label, type: 'property', detail: item.detail })),
      validFor: /^[\w-]*$/,
    }
  }

  // C5：`with:` 键位 → 该 `uses` 动作的 inputs（仅键位，值位不触发）
  if (parent?.key === 'with' && /^\s*[\w-]*$/.test(before)) {
    const uses = findUsesAbove(lines, parent.index)
    const spec = uses ? checks.find(check => check.uses === uses) : undefined
    if (!spec || spec.inputs.length === 0) return null
    return {
      from,
      options: spec.inputs.map(input => ({
        label: input.name,
        type: 'property',
        detail: inputDetail(input),
      })),
      validFor: /^[\w-]*$/,
    }
  }

  // 键位以外（值中间）不做关键字补全，避免打断普通输入；
  // 步骤条目行 `- ` 去掉前缀后按同层键位处理（回车自动带出 `- `，C3）
  const keyBefore = before.replace(/^(\s*)-\s+/, '$1')
  if (!/^\s*[\w-]*$/.test(keyBefore)) return null

  const parentKey = parent?.key ?? ''
  const { jobIds } = extractPipelineSymbols(doc)

  // C7：`steps:` 块 → 检查动作的步骤骨架
  if (parentKey === 'steps') {
    if (checks.length === 0) return null
    return {
      from,
      options: checks.map(check => ({
        label: `${check.title} 步骤`,
        type: 'snippet',
        detail: check.uses,
        apply: snippet(buildStepSnippet(check)),
      })),
    }
  }

  let pool: readonly string[]
  if (!parent) {
    // 顶层：关键字 + 完整 workflow 骨架（C7）
    const options_: Completion[] = keywordOptions(TOP_KEYWORDS)
    if (options.domain) {
      options_.push({
        label: '流水线骨架',
        type: 'snippet',
        detail: '完整 workflow 模板',
        apply: snippet(defaultWorkflowContent(options.domain)),
      })
    }
    return { from, options: options_ }
  }
  if (parentKey === 'on') pool = ON_KEYWORDS
  else if (parentKey === 'uses') pool = STEP_KEYWORDS
  else if (jobIds.includes(parentKey)) pool = JOB_KEYWORDS
  else return null

  return { from, options: keywordOptions(pool) }
}

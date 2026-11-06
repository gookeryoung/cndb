/** 流水线检查 DSL 语言支持 —— 关键字常量 / StreamLanguage 高亮 / 自动缩进（需求卡 0111 C1-C3）.
 *
 * 语法面与后端 `plugins/pipeline/services/dsl/parse.py` 的
 * `_TOP_KEYS / _ON_KEYS / _JOB_KEYS / _STEP_KEYS` 及 `models.SEVERITIES` 逐项对齐；
 * 常量表是高亮与自动完成的**单一来源**（C2），改语法先改这里。
 *
 * 高亮选型：自写轻量 StreamLanguage（先例 `design/designLang.ts`），不用官方
 * `@codemirror/lang-yaml`（它无法区分 DSL 关键字与普通键，见卡片未决问题②）。
 */

import { StreamLanguage, type StreamParser } from '@codemirror/language'
import type { EditorView } from '@codemirror/view'

/** 顶层键（C2，对齐 `_TOP_KEYS`） */
export const TOP_KEYWORDS = ['name', 'on', 'vars', 'jobs'] as const

/** 触发配置键（C2，对齐 `_ON_KEYS`） */
export const ON_KEYWORDS = ['manual', 'events', 'schedule'] as const

/** job 内键（C2，对齐 `_JOB_KEYS`） */
export const JOB_KEYWORDS = ['needs', 'if', 'steps'] as const

/** step 内键（C2，对齐 `_STEP_KEYS`） */
export const STEP_KEYWORDS = ['uses', 'with', 'severity', 'continue-on-error'] as const

/** 严重度取值（C2，对齐 `models.SEVERITIES`） */
export const SEVERITIES = ['error', 'warn', 'info'] as const

/** 关键字全集（供单测硬编码比对与高亮判定） */
export const DSL_KEYWORDS: string[] = [
  ...TOP_KEYWORDS,
  ...ON_KEYWORDS,
  ...JOB_KEYWORDS,
  ...STEP_KEYWORDS,
]

/** 关键字 → 中文一句话（补全 detail，C4） */
export const KEYWORD_DETAILS: Record<string, string> = {
  name: '流水线名称',
  on: '触发方式',
  vars: '流水线变量',
  jobs: '作业集合',
  manual: '是否允许手动触发',
  events: '订阅事件列表',
  schedule: '定时 cron 表达式',
  needs: '前置作业（DAG 依赖）',
  if: '执行条件表达式',
  steps: '检查步骤列表',
  uses: '引用的检查动作',
  with: '检查动作参数',
  severity: '命中后的严重度',
  'continue-on-error': '失败时是否继续后续步骤',
  error: '严重度：错误',
  warn: '严重度：告警',
  info: '严重度：提示',
}

const KEYWORD_SET = new Set<string>(DSL_KEYWORDS)
const SEVERITY_SET = new Set<string>(SEVERITIES)

/** 高亮状态：当前行的键（用于把 `uses` / `table` 的值着色为字符串） */
interface PipelineTokenState {
  key: string | null
}

const parser: StreamParser<PipelineTokenState> = {
  name: 'pipeline-dsl',
  startState: () => ({ key: null }),
  token(stream, state) {
    // 行首重置当前键（StreamParser 无 per-line 钩子）
    if (stream.pos === 0) state.key = null
    if (stream.eatSpace()) return null
    const ch = stream.peek() ?? ''
    // 注释：`#` 到行尾（与 YAML 一致）
    if (ch === '#') {
      stream.skipToEnd()
      return 'comment'
    }
    // 表达式 `${{ ... }}` 单独着色（C2）
    if (ch === '$' && stream.string.startsWith('${{', stream.pos)) {
      const end = stream.string.indexOf('}}', stream.pos + 3)
      if (end === -1) {
        stream.skipToEnd()
      } else {
        stream.pos = end + 2
      }
      return 'meta'
    }
    // 引号字符串（本行内闭合；跨行标量不常见，按行处理）
    if (ch === '"' || ch === "'") {
      const quote = ch
      stream.next()
      while (!stream.eol()) {
        const current = stream.next()
        if (current === '\\') {
          stream.next()
          continue
        }
        if (current === quote) break
      }
      return 'string'
    }
    // 列表短横（`- uses: ...`）；负号数字交给数值分支
    if (ch === '-' && /[\s[]/.test(stream.string[stream.pos + 1] ?? '')) {
      stream.next()
      return 'punctuation'
    }
    if ('[]{}'.includes(ch)) {
      stream.next()
      return 'bracket'
    }
    if (ch === ':' || ch === ',') {
      stream.next()
      return 'punctuation'
    }
    if (/[0-9]/.test(ch)) {
      stream.match(/^\d+(?:\.\d+)?/)
      return 'number'
    }
    // 标识符：字母 / 下划线 / 中文开头，后续可含数字与短横（`continue-on-error`、表名）
    if (/[A-Za-z_\u4e00-\u9fff]/.test(ch)) {
      stream.match(/^[A-Za-z0-9_\u4e00-\u9fff-]+/)
      const word = stream.current()
      // 后随 `:` → 键位：DSL 关键字用 keyword，其余（job 名 / 参数名）用属性色
      if (/^\s*:/.test(stream.string.slice(stream.pos))) {
        state.key = word
        return KEYWORD_SET.has(word) ? 'keyword' : 'propertyName'
      }
      if (SEVERITY_SET.has(word)) return 'atom'
      if (word === 'true' || word === 'false' || word === 'null') return 'bool'
      // uses 值 / 表名等标量统一按字符串色（C2）
      return 'string'
    }
    stream.next()
    return null
  },
  languageData: {
    commentTokens: { line: '#' },
  },
}

/** 流水线 DSL 语言实例（编辑器唯一入口） */
export const pipelineDslLanguage = StreamLanguage.define(parser)

/** 缩进单位：固定 2 空格，编辑器内的 Tab 也只写空格（C3） */
export const DSL_INDENT_UNIT = '  '

/** 去掉行尾注释（`#` 前必须有空白，避免误伤值里的 `#`），并清掉尾随空白 */
function stripLineComment(text: string): string {
  // 纯注释行原样保留：回车应继承当前缩进，而不是按「空行」回退
  if (text.trimStart().startsWith('#')) return text.trimEnd()
  return text.replace(/\s+#.*$/, '').trimEnd()
}

/** 回车后的下一行缩进：YAML 结构感知（C3-C5）.
 *
 * - 空行 / 纯空白行：回退一级，便于退出当前块；
 * - `key:` 结尾：进入下一层；
 * - `- key:`：子级对齐到列表内容列再进一级；
 * - 普通列表项：延续同一层 `- `；
 * - 裸 `-` / `- `：进入列表项内容层；
 * - 其余（含注释行）：继承当前行缩进。
 */
function nextDslIndent(before: string): string {
  const indent = /^[ \t]*/.exec(before)?.[0] ?? ''
  const content = stripLineComment(before)
  if (!content.trim()) {
    return indent.length >= DSL_INDENT_UNIT.length
      ? indent.slice(0, indent.length - DSL_INDENT_UNIT.length)
      : ''
  }

  const list = /^([ \t]*)-(?:[ \t]+|$)/.exec(content)
  if (list) {
    const base = list[1]
    const afterDash = content.slice(list[0].length).trimEnd()
    if (!afterDash) return `${base}${DSL_INDENT_UNIT}`
    if (afterDash.endsWith(':')) return `${base}${DSL_INDENT_UNIT}${DSL_INDENT_UNIT}`
    // 普通列表项：回车继续同一层列表（与 buildStepSnippet 的 6 空格层级同口径）
    return `${base}- `
  }

  if (content.endsWith(':')) return `${indent}${DSL_INDENT_UNIT}`
  return indent
}

/** 回车：按 YAML 结构计算下一行缩进；缩进只用空格（C3-C5）.
 *
 * 非空选区时按普通回车替换选区，不猜缩进。
 */
export function insertDslNewline(view: EditorView): boolean {
  const { state } = view
  const range = state.selection.main
  if (!range.empty) {
    view.dispatch(state.replaceSelection('\n'))
    return true
  }
  const line = state.doc.lineAt(range.head)
  const before = line.text.slice(0, range.head - line.from)
  view.dispatch(state.replaceSelection(`\n${nextDslIndent(before)}`))
  return true
}

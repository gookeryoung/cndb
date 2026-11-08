/** 结构 DSL（.cnmd）语言支持 —— CodeMirror StreamLanguage 高亮（ADR 0079 D11）.
 *
 * DSL v1 语法面（与后端 lexer 同口径，仅为高亮不做判定）：
 * - 语句关键字：param / module / system / use / as / constraint
 * - 布尔块：union / difference / intersection
 * - 变换：translate / rotate / scale / mirror
 * - 图元：box / cyl / sphere / cone / torus / tube
 * - 约束类型（ADR 0086 D4）：fixed / coincident / concentric / distance / angle
 * - 约束锚点（ADR 0086 D4）：origin / x / y / z
 * - 白名单函数与常量 PI；`//` 与 `/* *`` 注释；数值支持 `12` / `3.14` / `.5`。
 *
 * 常量表是高亮与自动完成的**单一来源**（需求卡 0110 C6），逐项对齐后端
 * `services/dsl/parse.py` 的 KEYWORD_* / BOOLEANS / TRANSFORMS / PRIMITIVES /
 * CONSTRAINT_TYPES / CONSTRAINT_ANCHORS / _FUNCTION_NAMES；改语法先改这里。
 */

import { StreamLanguage, type StreamParser } from '@codemirror/language'

/** 语句关键字（高亮为 keyword） */
export const STATEMENT_KEYWORDS = ['param', 'module', 'system', 'use', 'as', 'constraint'] as const

/** 布尔块关键字 */
export const BOOLEANS = ['union', 'difference', 'intersection'] as const

/** 变换关键字 */
export const TRANSFORMS = ['translate', 'rotate', 'scale', 'mirror'] as const

/** 六种图元（高亮为 typeName） */
export const PRIMITIVES = ['box', 'cyl', 'sphere', 'cone', 'torus', 'tube'] as const

/** 约束类型（ADR 0086 D4，高亮为 keyword） */
export const CONSTRAINT_TYPES = ['fixed', 'coincident', 'concentric', 'distance', 'angle'] as const

/** 约束引用端锚点（ADR 0086 D4，高亮为 atom） */
export const CONSTRAINT_ANCHORS = ['origin', 'x', 'y', 'z'] as const

/** 白名单函数 */
export const FUNCTIONS = [
  'sin', 'cos', 'tan', 'asin', 'acos', 'atan2', 'sqrt',
  'abs', 'min', 'max', 'pow', 'floor', 'ceil', 'round',
] as const

/** 白名单常量（与 FUNCTIONS 同属内建，高亮为 atom） */
export const CONSTANTS = ['PI'] as const

/** 顶层 / 结构关键字集合（高亮口径） */
const KEYWORDS = new Set<string>([...STATEMENT_KEYWORDS, ...BOOLEANS, ...TRANSFORMS, ...CONSTRAINT_TYPES])

const PRIMITIVE_SET = new Set<string>(PRIMITIVES)
const BUILTIN_SET = new Set<string>([...CONSTANTS, ...FUNCTIONS])
const ANCHOR_SET = new Set<string>(CONSTRAINT_ANCHORS)

/** 块注释状态：跨行 `/* ... *`` 需要 state（StreamParser per-line state） */
interface DslTokenState {
  inBlockComment: boolean
}

/** 判断是否构成标识符起始字符（与后端 lexer 同口径：字母 / 下划线） */
export function isIdentStart(ch: string): boolean {
  return /[A-Za-z_]/.test(ch)
}

/** 判断是否构成标识符后续字符 */
export function isIdentChar(ch: string): boolean {
  return /[A-Za-z0-9_]/.test(ch)
}

/** 按首字符分类标识符（关键字 / 图元 / 内建 / 普通名字）——单测直接覆盖该口径 */
export function identStyle(name: string): string {
  if (KEYWORDS.has(name)) return 'keyword'
  if (PRIMITIVE_SET.has(name)) return 'typeName'
  if (BUILTIN_SET.has(name) || ANCHOR_SET.has(name)) return 'atom'
  return 'variableName'
}

const parser: StreamParser<DslTokenState> = {
  name: 'cnmd',
  startState: () => ({ inBlockComment: false }),
  token(stream, state) {
    if (state.inBlockComment) {
      const end = stream.string.indexOf('*/', stream.pos)
      if (end === -1) {
        stream.skipToEnd()
      } else {
        stream.pos = end + 2
        state.inBlockComment = false
      }
      return 'comment'
    }
    // 空白
    if (stream.eatSpace()) return null
    const ch = stream.peek() ?? ''
    // 行注释
    if (ch === '/' && stream.string[stream.pos + 1] === '/') {
      stream.skipToEnd()
      return 'comment'
    }
    // 块注释
    if (ch === '/' && stream.string[stream.pos + 1] === '*') {
      state.inBlockComment = true
      stream.pos += 2
      return this.token(stream, state)
    }
    // 数值：12 / 3.14 / .5（不支持科学计数，与后端 lexer 一致）
    if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(stream.string[stream.pos + 1] ?? ''))) {
      stream.match(/^\d*\.?\d*/)
      return 'number'
    }
    // 标识符 / 关键字 / 图元 / 内建
    if (isIdentStart(ch)) {
      stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)
      return identStyle(stream.current())
    }
    // 标点
    if ('[]{}()'.includes(ch)) {
      stream.next()
      return 'bracket'
    }
    if ('+-*/%='.includes(ch)) {
      stream.next()
      return 'operator'
    }
    if (ch === ',') {
      stream.next()
      return 'punctuation'
    }
    stream.next()
    return null
  },
  languageData: {
    commentTokens: { line: '//', block: { open: '/*', close: '*/' } },
    // 只配对括号，不自动补引号，避免干扰 use 字符串补全（0127 C4）
    closeBrackets: { brackets: ['(', '[', '{'] },
    // 输入 / 粘贴出独占一行的 `}` 时按缩进服务自动回退（0127 C4）
    indentOnInput: /^\s*\}$/,
  },
}

/** 结构 DSL 语言实例（编辑器唯一入口） */
export const cnDslLanguage = StreamLanguage.define(parser)

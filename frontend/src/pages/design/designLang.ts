/** 结构 DSL（.cnmd）语言支持 —— CodeMirror StreamLanguage 高亮（ADR 0079 D11）.
 *
 * DSL v1 语法面（与后端 lexer 同口径，仅为高亮不做判定）：
 * - 语句关键字：param / module
 * - 布尔块：union / difference / intersection
 * - 变换：translate / rotate / scale / mirror
 * - 图元：box / cyl / sphere / cone / torus / tube
 * - 白名单函数与常量 PI；`//` 与 `/* *`` 注释；数值支持 `12` / `3.14` / `.5`。
 */

import { StreamLanguage, type StreamParser } from '@codemirror/language'

/** 语句与结构关键字（高亮为 keyword） */
const KEYWORDS = new Set([
  'param', 'module',
  'union', 'difference', 'intersection',
  'translate', 'rotate', 'scale', 'mirror',
])

/** 六种图元（高亮为 typeName） */
const PRIMITIVES = new Set(['box', 'cyl', 'sphere', 'cone', 'torus', 'tube'])

/** 白名单函数与常量（高亮为 atom） */
const BUILTINS = new Set([
  'PI', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan2', 'sqrt',
  'abs', 'min', 'max', 'pow', 'floor', 'ceil', 'round',
])

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
  if (PRIMITIVES.has(name)) return 'typeName'
  if (BUILTINS.has(name)) return 'atom'
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
  },
}

/** 结构 DSL 语言实例（编辑器唯一入口） */
export const cnDslLanguage = StreamLanguage.define(parser)

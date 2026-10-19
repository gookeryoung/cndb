/** Markdown 代码块的轻量语法高亮（零依赖，词法级）。
 *
 * 为什么不引 highlight.js / shiki：文档页 chunk 有体积预算（docs/BUNDLE_BUDGET.md），
 * 而文档里的代码块以常见语言短片段为主。这里用一套配置驱动的扫描器覆盖
 * JS/TS、Python、JSON、Shell、SQL、HTML/XML、CSS、YAML、Go、Java、Rust、C 系，
 * 输出「绝对偏移 + token 类型」，由预览（`CodeBlock`）与实时编辑器
 * （CodeMirror 装饰）共用，颜色统一走 `index.css` 的 `--cn-code-*` 变量。
 *
 * 设计约束：
 * - **线性扫描**：每个 token 只前进不回退，单次 tokenize 复杂度 O(n)；
 * - **不抛错**：未闭合字符串 / 注释一律吃到文末，编辑器中途输入不会崩；
 * - **未知语言**返回空数组（渲染为纯文本），不猜语法。
 */

export type CodeTokenType =
  | 'keyword'
  | 'string'
  | 'comment'
  | 'number'
  | 'boolean'
  | 'function'
  | 'type'
  | 'operator'
  | 'punctuation'
  | 'tag'
  | 'attr'
  | 'builtin'
  | 'meta'
  | 'property'
  | 'variable'

/** token 在源码中的半开区间 `[from, to)`；text 由调用方按偏移切片 */
export interface CodeToken {
  from: number
  to: number
  type: CodeTokenType
}

// ── 语言注册表 ────────────────────────────────────────────

interface LanguageSpec {
  /** 行注释起始符（如 `//`、`#`、`--`） */
  line?: string[]
  /** 块注释起止对 */
  block?: Array<[string, string]>
  /** 单行字符串引号（可多条） */
  quotes?: string[]
  /** 允许跨行的引号（模板串 / 三引号） */
  multilineQuotes?: string[]
  /** 关键字（空格分隔，便于阅读） */
  keywords?: string
  /** 字面量常量（true / false / None …） */
  literals?: string
  /** 内建对象 / 函数 */
  builtins?: string
  /** 关键字大小写不敏感（SQL） */
  ignoreCase?: boolean
  /** 形如 `key:` 的标识符着色为 property（JSON / YAML / CSS） */
  propKeys?: boolean
  /** 字符串后跟 `:` 也视为 property（JSON 的 "key":） */
  propStringKeys?: boolean
  /** `#` 仅行首/空白后算注释（YAML 的 `#` 也可能出现在值里） */
  lineStartOnlyComment?: boolean
  /** `$VAR` 变量 */
  dollarVars?: boolean
  /** `@decorator` */
  decorators?: boolean
  /** `@media` 这类 at-rule */
  atRules?: boolean
  /** `#fff` 颜色值 */
  colors?: boolean
  /** 数字后缀单位（`10px`） */
  units?: boolean
  /** 首字母大写的标识符视为类型 */
  typesCapitalized?: boolean
  /** 标识符允许连字符（CSS 的 `min-width`） */
  hyphenIdents?: boolean
  /** `&anchor` / `*alias` */
  anchors?: boolean
}

const JS_KEYWORDS = `
  await async break case catch class const continue debugger default delete do else enum export extends
  finally for from function get if implements import in instanceof interface let new of package private
  protected public readonly return set static super switch this throw try type typeof var void while with
  yield declare namespace module abstract as satisfies keyof infer is
`
const JS_BUILTINS = `
  console window document Math JSON Promise Array Object String Number Boolean Map Set Date RegExp Symbol
  Error setTimeout setInterval clearTimeout fetch globalThis parseInt parseFloat Infinity
`
const PY_KEYWORDS = `
  def class return if elif else for while import from as with try except finally raise pass break continue
  lambda yield global nonlocal assert del in is not and or async await match case
`
const PY_BUILTINS = `
  print len range str int float list dict set tuple bool open isinstance super enumerate zip map filter
  sorted sum min max abs type repr self cls
`
const SHELL_KEYWORDS = `
  if then else elif fi for while until do done case esac function in return local export readonly unset
  set shift source alias break continue trap
`
const SHELL_BUILTINS = 'echo cd pwd ls cat grep sed awk curl git pnpm npm make sudo exit test read printf'
const SQL_KEYWORDS = `
  select from where join left right inner outer full on group by order having limit offset insert into
  values update set delete create table alter drop index view as and or not null is in like between
  distinct union all case when then else end primary key foreign references default unique constraint
  begin commit rollback grant revoke with recursive over partition window exists cascade
`
const SQL_BUILTINS = 'count sum avg min max coalesce cast concat now current_date lower upper length'
const GO_KEYWORDS = `
  package import func var const type struct interface map chan go defer select range return if else for
  switch case default break continue fallthrough goto nil true false iota
`
const JAVA_KEYWORDS = `
  public private protected class interface extends implements static final abstract void int long short
  byte char float double boolean if else for while do switch case default break continue return new try
  catch finally throw throws import package this super null true false instanceof enum record var
`
const RUST_KEYWORDS = `
  fn let mut pub impl struct enum trait use mod match if else for while loop return break continue
  where as const static ref move async await dyn unsafe extern crate self Self super type in
`
const C_KEYWORDS = `
  auto break case char const continue default do double else enum extern float for goto if inline int
  long register return short signed sizeof static struct switch typedef union unsigned void volatile while
  class public private protected template typename namespace using new delete virtual override nullptr
  true false bool string vector include
`
const YAML_LITERALS = 'true false null yes no on off'

const SPECS: Record<string, LanguageSpec> = {
  js: {
    line: ['//'],
    block: [['/*', '*/']],
    quotes: ['"', "'"],
    multilineQuotes: ['`'],
    keywords: JS_KEYWORDS,
    literals: 'true false null undefined NaN',
    builtins: JS_BUILTINS,
    typesCapitalized: true,
  },
  ts: {
    line: ['//'],
    block: [['/*', '*/']],
    quotes: ['"', "'"],
    multilineQuotes: ['`'],
    keywords: JS_KEYWORDS,
    literals: 'true false null undefined NaN',
    builtins: JS_BUILTINS,
    typesCapitalized: true,
  },
  json: {
    quotes: ['"'],
    literals: 'true false null',
    propKeys: true,
    propStringKeys: true,
  },
  py: {
    line: ['#'],
    quotes: ['"', "'"],
    multilineQuotes: ['"""', "'''"],
    keywords: PY_KEYWORDS,
    literals: 'True False None',
    builtins: PY_BUILTINS,
    decorators: true,
    typesCapitalized: true,
  },
  bash: {
    line: ['#'],
    quotes: ['"', "'", '`'],
    keywords: SHELL_KEYWORDS,
    builtins: SHELL_BUILTINS,
    literals: 'true false',
    dollarVars: true,
  },
  sql: {
    line: ['--'],
    block: [['/*', '*/']],
    quotes: ["'", '"'],
    keywords: SQL_KEYWORDS,
    literals: 'null true false',
    builtins: SQL_BUILTINS,
    ignoreCase: true,
  },
  html: { block: [['<!--', '-->']] },
  css: {
    block: [['/*', '*/']],
    // SCSS 的 `//` 注释只在行首成立：无引号 URL（url(https://…)）不能被当成注释
    line: ['//'],
    lineStartOnlyComment: true,
    quotes: ['"', "'"],
    propKeys: true,
    atRules: true,
    colors: true,
    units: true,
    hyphenIdents: true,
  },
  yaml: {
    line: ['#'],
    quotes: ['"', "'"],
    literals: YAML_LITERALS,
    propKeys: true,
    propStringKeys: true,
    lineStartOnlyComment: true,
    anchors: true,
  },
  go: {
    line: ['//'],
    block: [['/*', '*/']],
    quotes: ['"', "'"],
    multilineQuotes: ['`'],
    keywords: GO_KEYWORDS,
    builtins: 'fmt make len append string int float64 error',
    typesCapitalized: true,
  },
  java: {
    line: ['//'],
    block: [['/*', '*/']],
    quotes: ['"', "'"],
    keywords: JAVA_KEYWORDS,
    builtins: 'System String Integer List Map Set',
    typesCapitalized: true,
  },
  rust: {
    line: ['//'],
    block: [['/*', '*/']],
    quotes: ['"'],
    keywords: RUST_KEYWORDS,
    builtins: 'println vec format String Vec Option Result Some None Ok Err',
    typesCapitalized: true,
  },
  clike: {
    line: ['//'],
    block: [['/*', '*/']],
    quotes: ['"', "'"],
    multilineQuotes: ['`'],
    keywords: C_KEYWORDS,
    typesCapitalized: true,
  },
}

/** Markdown 语言标识 → 注册表 key（fence info 里写的别名都收在这里） */
const ALIASES: Record<string, string> = {
  javascript: 'js',
  jsx: 'js',
  mjs: 'js',
  cjs: 'js',
  node: 'js',
  typescript: 'ts',
  tsx: 'ts',
  jsonc: 'json',
  json5: 'json',
  python: 'py',
  python3: 'py',
  py3: 'py',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  console: 'bash',
  shellscript: 'bash',
  psql: 'sql',
  postgres: 'sql',
  postgresql: 'sql',
  mysql: 'sql',
  sqlite: 'sql',
  htm: 'html',
  xml: 'html',
  svg: 'html',
  vue: 'html',
  scss: 'css',
  less: 'css',
  yml: 'yaml',
  golang: 'go',
  rs: 'rust',
  c: 'clike',
  h: 'clike',
  cc: 'clike',
  cpp: 'clike',
  'c++': 'clike',
  cxx: 'clike',
  hpp: 'clike',
  cs: 'clike',
  csharp: 'clike',
  kotlin: 'clike',
  kt: 'clike',
  swift: 'clike',
  php: 'clike',
  objc: 'clike',
}

/** fence info 语言标识标签（预览代码块头部展示） */
const LABELS: Record<string, string> = {
  js: 'JavaScript',
  ts: 'TypeScript',
  json: 'JSON',
  py: 'Python',
  bash: 'Shell',
  sql: 'SQL',
  html: 'HTML',
  css: 'CSS',
  yaml: 'YAML',
  go: 'Go',
  java: 'Java',
  rust: 'Rust',
  clike: 'C/C++',
}

/** 取语言 key：支持 `language-ts`、`ts title="x"`、Pandoc 风格 `{.python}` */
export function normalizeLanguage(raw?: string | null): string | null {
  if (!raw) return null
  const key = raw
    .trim()
    .toLowerCase()
    .replace(/^language-/, '')
    .replace(/^\{\.?/, '')
    .split(/[\s,}]/)[0]
  if (!key) return null
  if (SPECS[key]) return key
  return ALIASES[key] ?? null
}

/** 语言展示名（未知语言返回 null，由调用方回退成「代码」） */
export function languageLabel(language?: string | null): string | null {
  const key = normalizeLanguage(language)
  return key ? LABELS[key] ?? key.toUpperCase() : null
}

// ── 扫描工具 ──────────────────────────────────────────────

const IDENT_RE = /^[\p{L}_$][\p{L}\p{N}_$]*/u
/** CSS 标识符允许连字符（`min-width` / `-webkit-box`） */
const HYPHEN_IDENT_RE = /^-?[\p{L}_$][\p{L}\p{N}_$-]*/u
const NUMBER_RE =
  /^(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d+)?)/
const UNIT_RE = /^(?:%|[a-zA-Z]+)/
const ATTR_RE = /^[^\s=>/]+/
const TAG_RE = /^[A-Za-z][\w:.-]*/
const ENTITY_RE = /^&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);/
const OPERATOR_CHARS = new Set(['+', '-', '*', '/', '%', '=', '<', '>', '!', '&', '|', '^', '~', '?', ':'])
const PUNCTUATION_CHARS = new Set(['(', ')', '{', '}', '[', ']', ',', ';', '.', '@'])
const WORD_CHARS = /[\p{L}\p{N}_$]/u

function words(raw?: string): Set<string> {
  return new Set((raw ?? '').split(/\s+/).filter(Boolean))
}

interface LangRuntime {
  spec: LanguageSpec
  keywords: Set<string>
  literals: Set<string>
  builtins: Set<string>
}

const RUNTIME = new Map<string, LangRuntime>(
  Object.entries(SPECS).map(([key, spec]) => [
    key,
    {
      spec,
      keywords: words(spec.ignoreCase ? spec.keywords?.toLowerCase() : spec.keywords),
      literals: words(spec.ignoreCase ? spec.literals?.toLowerCase() : spec.literals),
      builtins: words(spec.ignoreCase ? spec.builtins?.toLowerCase() : spec.builtins),
    },
  ]),
)

/** 找下一个非空白字符下标（看关键字后面是不是 `(` / `:`） */
function nextNonSpace(code: string, from: number): number {
  let i = from
  while (i < code.length && /\s/.test(code[i])) i++
  return i
}

/** 扫描引号字符串，返回闭合后的下标（未闭合吃到文末 / 行尾） */
function scanQuoted(code: string, start: number, quote: string, multiline: boolean): number {
  let i = start + quote.length
  while (i < code.length) {
    const ch = code[i]
    if (ch === '\\') {
      i += 2
      continue
    }
    if (code.startsWith(quote, i)) return i + quote.length
    if (ch === '\n' && !multiline) return i
    i++
  }
  return code.length
}

/** 行注释是否成立：`#` 在 YAML 里只有行首/空白后才是注释 */
function isLineCommentAt(code: string, i: number, lineStartOnly: boolean): boolean {
  if (!lineStartOnly) return true
  if (i === 0) return true
  return /\s/.test(code[i - 1])
}

function scanGeneric(code: string, runtime: LangRuntime, tokens: CodeToken[]): void {
  const { spec, keywords, literals, builtins } = runtime
  const n = code.length
  const blocks = spec.block ?? []
  const lineMarks = spec.line ?? []
  // 更长的定界符优先（`"""` 先于 `"`）
  const quoteMarks = [...(spec.multilineQuotes ?? []), ...(spec.quotes ?? [])].sort(
    (a, b) => b.length - a.length,
  )
  const atCommentStart = (pos: number) =>
    blocks.some(([open]) => code.startsWith(open, pos)) ||
    lineMarks.some(mark => code.startsWith(mark, pos))
  const push = (from: number, to: number, type: CodeTokenType) => {
    if (to > from) tokens.push({ from, to, type })
  }
  let i = 0
  while (i < n) {
    // 换行与空白不产生 token
    if (code[i] === '\n' || /\s/.test(code[i])) {
      i++
      continue
    }

    // 块注释优先于行注释（`/*` 与 `//` 不重叠，顺序只为可读性）
    let consumed = false
    for (const [open, close] of blocks) {
      if (!code.startsWith(open, i)) continue
      const end = code.indexOf(close, i + open.length)
      const stop = end === -1 ? n : end + close.length
      push(i, stop, 'comment')
      i = stop
      consumed = true
      break
    }
    if (consumed) continue

    for (const mark of lineMarks) {
      if (code.startsWith(mark, i) && isLineCommentAt(code, i, spec.lineStartOnlyComment === true)) {
        const end = code.indexOf('\n', i)
        const stop = end === -1 ? n : end
        push(i, stop, 'comment')
        i = stop
        consumed = true
        break
      }
    }
    if (consumed) continue

    // 字符串：先匹配更长的定界符（`"""` 先于 `"`）
    for (const quote of quoteMarks) {
      if (!code.startsWith(quote, i)) continue
      const multiline = quote.length > 1 || (spec.multilineQuotes ?? []).includes(quote)
      const stop = scanQuoted(code, i, quote, multiline)
      // `"key":` 这类 JSON 键名单独着色
      const after = nextNonSpace(code, stop)
      const isKey = spec.propStringKeys === true && code[after] === ':' && code[after + 1] !== ':'
      push(i, stop, isKey ? 'property' : 'string')
      i = stop
      consumed = true
      break
    }
    if (consumed) continue

    // `#fff` 颜色值
    if (spec.colors && code[i] === '#') {
      const hex = /^#[0-9a-fA-F]{3,8}\b/.exec(code.slice(i))
      if (hex) {
        push(i, i + hex[0].length, 'number')
        i += hex[0].length
        continue
      }
    }

    // `@media` / `@decorator`
    if (code[i] === '@' && (spec.atRules || spec.decorators)) {
      const at = IDENT_RE.exec(code.slice(i + 1))
      if (at) {
        push(i, i + 1 + at[0].length, 'meta')
        i += 1 + at[0].length
        continue
      }
    }

    // `$VAR`
    if (spec.dollarVars && code[i] === '$') {
      const variable = /^\$\{[^}]*\}|^\$[\p{L}\p{N}_]+/u.exec(code.slice(i))
      if (variable) {
        push(i, i + variable[0].length, 'variable')
        i += variable[0].length
        continue
      }
    }

    // `&anchor` / `*alias`
    if (spec.anchors && (code[i] === '&' || code[i] === '*')) {
      const anchor = IDENT_RE.exec(code.slice(i + 1))
      if (anchor) {
        push(i, i + 1 + anchor[0].length, 'meta')
        i += 1 + anchor[0].length
        continue
      }
    }

    // 数字（含 0x / 0b 与指数；CSS 再吃单位）
    if (/\d/.test(code[i]) || (code[i] === '.' && /\d/.test(code[i + 1] ?? ''))) {
      const num = NUMBER_RE.exec(code.slice(i))
      if (num) {
        let stop = i + num[0].length
        if (spec.units) {
          const unit = UNIT_RE.exec(code.slice(stop))
          if (unit) stop += unit[0].length
        }
        push(i, stop, 'number')
        i = stop
        continue
      }
    }

    // 标识符：关键字 / 字面量 / 内建 / 函数调用 / 键名 / 类型
    const ident = (spec.hyphenIdents ? HYPHEN_IDENT_RE : IDENT_RE).exec(code.slice(i))
    if (ident) {
      const raw = ident[0]
      const stop = i + raw.length
      const word = spec.ignoreCase ? raw.toLowerCase() : raw
      const after = nextNonSpace(code, stop)
      if (literals.has(word)) push(i, stop, 'boolean')
      else if (keywords.has(word)) push(i, stop, 'keyword')
      else if (builtins.has(word)) push(i, stop, 'builtin')
      else if (spec.propKeys && code[after] === ':' && code[after + 1] !== ':') push(i, stop, 'property')
      else if (code[after] === '(') push(i, stop, 'function')
      else if (spec.typesCapitalized && /^\p{Lu}/u.test(raw)) push(i, stop, 'type')
      i = stop
      continue
    }

    // 运算符连写（`===` / `=>` / `**`）与标点；遇到注释起始符立即让位
    if (OPERATOR_CHARS.has(code[i])) {
      let stop = i
      while (stop < n && OPERATOR_CHARS.has(code[stop]) && !(stop > i && atCommentStart(stop))) stop++
      push(i, stop, 'operator')
      i = stop
      continue
    }
    if (PUNCTUATION_CHARS.has(code[i])) {
      push(i, i + 1, 'punctuation')
      i++
      continue
    }

    // 纯文本（中文、emoji 等）：跳过即可
    i++
    while (i < n && !WORD_CHARS.test(code[i]) && !OPERATOR_CHARS.has(code[i]) && !PUNCTUATION_CHARS.has(code[i]) && !/\s/.test(code[i])) {
      i++
    }
  }
}

/** HTML / XML：标签名、属性名、属性值、注释、实体分别着色 */
function scanHtml(code: string, tokens: CodeToken[]): void {
  const n = code.length
  const push = (from: number, to: number, type: CodeTokenType) => {
    if (to > from) tokens.push({ from, to, type })
  }
  let i = 0
  while (i < n) {
    if (code.startsWith('<!--', i)) {
      const end = code.indexOf('-->', i + 4)
      const stop = end === -1 ? n : end + 3
      push(i, stop, 'comment')
      i = stop
      continue
    }
    if (code.startsWith('<![CDATA[', i)) {
      const end = code.indexOf(']]>', i + 9)
      const stop = end === -1 ? n : end + 3
      push(i, stop, 'comment')
      i = stop
      continue
    }
    if (code.startsWith('<!', i)) {
      const end = code.indexOf('>', i + 2)
      const stop = end === -1 ? n : end + 1
      push(i, stop, 'meta')
      i = stop
      continue
    }
    if (code[i] === '&') {
      const entity = ENTITY_RE.exec(code.slice(i))
      if (entity) {
        push(i, i + entity[0].length, 'builtin')
        i += entity[0].length
        continue
      }
    }
    if (code[i] !== '<') {
      i++
      continue
    }

    // 开始 / 结束标签：< 名称 attr="值" >
    let j = i
    push(j, j + 1, 'punctuation')
    j++
    if (code[j] === '/') {
      push(j, j + 1, 'punctuation')
      j++
    }
    const tag = TAG_RE.exec(code.slice(j))
    if (tag) {
      push(j, j + tag[0].length, 'tag')
      j += tag[0].length
    }
    while (j < n && code[j] !== '>') {
      const ch = code[j]
      if (/\s/.test(ch) || ch === '/') {
        j++
        continue
      }
      if (ch === '"' || ch === "'") {
        const stop = scanQuoted(code, j, ch, true)
        push(j, stop, 'string')
        j = stop
        continue
      }
      if (ch === '=') {
        push(j, j + 1, 'operator')
        j++
        continue
      }
      const attr = ATTR_RE.exec(code.slice(j))
      if (attr) {
        push(j, j + attr[0].length, 'attr')
        j += attr[0].length
        continue
      }
      j++
    }
    if (code[j] === '>') {
      push(j, j + 1, 'punctuation')
      j++
    }
    i = j
  }
}

/**
 * 对代码文本做词法高亮。
 *
 * @param code 代码原文
 * @param language fence info 里的语言标识（可空 / 未知 → 返回空数组）
 * @returns 按出现顺序排列、互不重叠的 token 区间
 */
export function highlightCode(code: string, language?: string | null): CodeToken[] {
  if (!code) return []
  const key = normalizeLanguage(language)
  if (!key) return []
  const tokens: CodeToken[] = []
  if (key === 'html') {
    scanHtml(code, tokens)
    return tokens
  }
  const runtime = RUNTIME.get(key)
  if (!runtime) return []
  scanGeneric(code, runtime, tokens)
  return tokens
}

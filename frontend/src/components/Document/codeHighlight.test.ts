/** codeHighlight 单测 — 覆盖语言归一化、各语言词法边界与容错（未闭合不抛错） */

import { describe, expect, it } from 'vitest'
import { highlightCode, languageLabel, normalizeLanguage } from './codeHighlight'
import type { CodeToken } from './codeHighlight'

/** 把 token 还原成 [类型, 原文] 便于断言 */
function pieces(code: string, language?: string | null): Array<[string, string]> {
  return highlightCode(code, language).map((t: CodeToken) => [t.type, code.slice(t.from, t.to)])
}

describe('normalizeLanguage', () => {
  it('识别注册表语言与常见别名', () => {
    expect(normalizeLanguage('ts')).toBe('ts')
    expect(normalizeLanguage('TypeScript')).toBe('ts')
    expect(normalizeLanguage('python3')).toBe('py')
    expect(normalizeLanguage('c++')).toBe('clike')
    expect(normalizeLanguage('language-sql')).toBe('sql')
    expect(normalizeLanguage('js title="a"')).toBe('js')
    expect(normalizeLanguage('{.python}')).toBe('py')
  })

  it('空值 / 未知语言返回 null', () => {
    expect(normalizeLanguage(undefined)).toBeNull()
    expect(normalizeLanguage(null)).toBeNull()
    expect(normalizeLanguage('  ')).toBeNull()
    expect(normalizeLanguage('brainfuck')).toBeNull()
  })
})

describe('languageLabel', () => {
  it('已知语言给展示名，未知给 null', () => {
    expect(languageLabel('js')).toBe('JavaScript')
    expect(languageLabel('yml')).toBe('YAML')
    expect(languageLabel('nope')).toBeNull()
    expect(languageLabel(null)).toBeNull()
  })
})

describe('highlightCode — JavaScript', () => {
  it('关键字 / 字符串 / 注释 / 数字 / 函数调用 / 类型', () => {
    const code = '// 注释\nconst n = 42\nfunction greet(a: string) { return new Map() }'
    const tokens = pieces(code, 'js')
    expect(tokens).toContainEqual(['comment', '// 注释'])
    expect(tokens).toContainEqual(['keyword', 'const'])
    expect(tokens).toContainEqual(['number', '42'])
    expect(tokens).toContainEqual(['keyword', 'function'])
    expect(tokens).toContainEqual(['function', 'greet'])
    expect(tokens).toContainEqual(['builtin', 'Map'])
    expect(tokens).toContainEqual(['keyword', 'return'])
  })

  it('模板串跨行、块注释吃到闭合符', () => {
    const code = 'const s = `a\nb`\n/* note\nstill */ x'
    const tokens = pieces(code, 'ts')
    expect(tokens).toContainEqual(['string', '`a\nb`'])
    expect(tokens).toContainEqual(['comment', '/* note\nstill */'])
  })

  it('运算符后面紧跟行注释时不吞注释', () => {
    const tokens = pieces('a+-// note', 'js')
    expect(tokens).toContainEqual(['comment', '// note'])
  })
})

describe('highlightCode — Python / JSON / SQL / Shell', () => {
  it('Python：三引号字符串、装饰器、内建函数', () => {
    const code = '@decorator\ndef f():\n    """文档"""\n    print(len([1]))'
    const tokens = pieces(code, 'py')
    expect(tokens).toContainEqual(['meta', '@decorator'])
    expect(tokens).toContainEqual(['keyword', 'def'])
    expect(tokens).toContainEqual(['string', '"""文档"""'])
    expect(tokens).toContainEqual(['builtin', 'print'])
    expect(tokens).toContainEqual(['number', '1'])
  })

  it('JSON：键名 property、布尔字面量、字符串值', () => {
    const tokens = pieces('{"a": true, "b": "x"}', 'json')
    expect(tokens).toContainEqual(['property', '"a"'])
    expect(tokens).toContainEqual(['boolean', 'true'])
    expect(tokens).toContainEqual(['string', '"x"'])
  })

  it('SQL：关键字大小写不敏感', () => {
    const tokens = pieces('SELECT count(*) FROM t WHERE id = 1', 'sql')
    expect(tokens).toContainEqual(['keyword', 'SELECT'])
    expect(tokens).toContainEqual(['builtin', 'count'])
    expect(tokens).toContainEqual(['keyword', 'FROM'])
    expect(tokens).toContainEqual(['keyword', 'WHERE'])
  })

  it('Shell：$VAR / ${VAR} 变量与 # 注释', () => {
    const tokens = pieces('echo $HOME ${PATH}\n# 注释', 'bash')
    expect(tokens).toContainEqual(['builtin', 'echo'])
    expect(tokens).toContainEqual(['variable', '$HOME'])
    expect(tokens).toContainEqual(['variable', '${PATH}'])
    expect(tokens).toContainEqual(['comment', '# 注释'])
  })
})

describe('highlightCode — HTML / CSS / YAML', () => {
  it('HTML：标签 / 属性 / 属性值 / 注释 / 实体', () => {
    const code = '<!-- c -->\n<div class="box">a &amp; b</div>'
    const tokens = pieces(code, 'html')
    expect(tokens).toContainEqual(['comment', '<!-- c -->'])
    expect(tokens).toContainEqual(['tag', 'div'])
    expect(tokens).toContainEqual(['attr', 'class'])
    expect(tokens).toContainEqual(['string', '"box"'])
    expect(tokens).toContainEqual(['builtin', '&amp;'])
  })

  it('CSS：属性名 / 颜色 / 带单位数值 / at-rule', () => {
    const code = '@media (min-width: 640px) { .a { color: #fff; margin: 10px } }'
    const tokens = pieces(code, 'css')
    expect(tokens).toContainEqual(['meta', '@media'])
    expect(tokens).toContainEqual(['property', 'min-width'])
    expect(tokens).toContainEqual(['property', 'color'])
    expect(tokens).toContainEqual(['number', '#fff'])
    expect(tokens).toContainEqual(['number', '10px'])
  })

  it('CSS：无引号 URL 里的 // 不算注释', () => {
    const tokens = pieces('a { background: url(https://x.test/y.png) }', 'css')
    expect(tokens.some(([type]) => type === 'comment')).toBe(false)
  })

  it('YAML：键名 / 布尔值 / 锚点 / 注释只在空白后成立', () => {
    const code = 'name: demo\nflag: true\nbase: &anchor\nurl: a#b # 注释'
    const tokens = pieces(code, 'yaml')
    expect(tokens).toContainEqual(['property', 'name'])
    expect(tokens).toContainEqual(['boolean', 'true'])
    expect(tokens).toContainEqual(['meta', '&anchor'])
    // `a#b` 里的 # 不是注释，尾部空白后的才是
    expect(tokens).toContainEqual(['comment', '# 注释'])
    expect(tokens.some(([type, text]) => type === 'comment' && text === '# 注释')).toBe(true)
  })
})

describe('highlightCode — 容错', () => {
  it('未知语言 / 空文本返回空数组', () => {
    expect(highlightCode('const a = 1', 'brainfuck')).toEqual([])
    expect(highlightCode('', 'js')).toEqual([])
  })

  it('未闭合字符串与块注释吃到文末但不抛错', () => {
    expect(pieces('"abc', 'js')).toEqual([['string', '"abc']])
    expect(pieces('/* abc', 'js')).toEqual([['comment', '/* abc']])
    expect(pieces("'abc\nnext", 'py')).toEqual([['string', "'abc"]])
  })

  it('token 区间互不重叠且有序', () => {
    const code = 'const a = "x" // c\nconst b = [1, 2]'
    const tokens = highlightCode(code, 'js')
    expect(tokens.length).toBeGreaterThan(0)
    for (let i = 1; i < tokens.length; i++) {
      expect(tokens[i].from).toBeGreaterThanOrEqual(tokens[i - 1].to)
    }
  })
})

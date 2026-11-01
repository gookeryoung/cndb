/** 结构 DSL 高亮分词测试 —— 关键字 / 图元 / 内建 / 数值 / 注释口径（ADR 0079 D11）. */

import { describe, expect, it } from 'vitest'
import { cnDslLanguage, identStyle, isIdentChar, isIdentStart } from './designLang'

describe('designLang 分词口径', () => {
  it('语句与结构关键字高亮为 keyword', () => {
    for (const keyword of [
      'param', 'module',
      'union', 'difference', 'intersection',
      'translate', 'rotate', 'scale', 'mirror',
    ]) {
      expect(identStyle(keyword)).toBe('keyword')
    }
  })

  it('六种图元高亮为 typeName', () => {
    for (const primitive of ['box', 'cyl', 'sphere', 'cone', 'torus', 'tube']) {
      expect(identStyle(primitive)).toBe('typeName')
    }
  })

  it('白名单函数与 PI 高亮为 atom', () => {
    for (const builtin of ['PI', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan2', 'sqrt', 'abs', 'min', 'max', 'pow', 'floor', 'ceil', 'round']) {
      expect(identStyle(builtin)).toBe('atom')
    }
  })

  it('参数名 / 模块名 / 未知标识符高亮为 variableName', () => {
    expect(identStyle('width')).toBe('variableName')
    expect(identStyle('plate')).toBe('variableName')
    expect(identStyle('hole_d')).toBe('variableName')
  })

  it('标识符字符口径与后端 lexer 一致：字母 / 下划线起始，数字可续', () => {
    expect(isIdentStart('a')).toBe(true)
    expect(isIdentStart('_')).toBe(true)
    expect(isIdentStart('9')).toBe(false)
    expect(isIdentStart(']')).toBe(false)
    expect(isIdentChar('9')).toBe(true)
    expect(isIdentChar('_')).toBe(true)
    expect(isIdentChar('-')).toBe(false)
  })

  it('语言实例可创建且名称为 cnmd', () => {
    expect(cnDslLanguage.name).toBe('cnmd')
  })
})

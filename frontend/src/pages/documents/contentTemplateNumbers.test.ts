import { describe, expect, it } from 'vitest'
import { hasHeadingNumbers, stripHeadingNumbers } from './contentTemplateNumbers'

describe('contentTemplateNumbers（ADR 0186 C6）', () => {
  it('剥掉中文序号标题', () => {
    const input = '## 一、项目基本信息\n\n正文\n\n## 二、立项依据\n'
    const result = stripHeadingNumbers(input)
    expect(result.changed).toBe(2)
    expect(result.text).toBe('## 项目基本信息\n\n正文\n\n## 立项依据\n')
  })

  it('剥掉阿拉伯多级序号标题', () => {
    const input = '### 3.1 总体目标\n\n### 3.2 具体目标\n'
    const result = stripHeadingNumbers(input)
    expect(result.changed).toBe(2)
    expect(result.text).toBe('### 总体目标\n\n### 具体目标\n')
  })

  it('剥掉章节式序号与（一）式序号', () => {
    const input = '## 第一章 概述\n\n## （一）背景\n\n## 1. 范围\n'
    const result = stripHeadingNumbers(input)
    expect(result.changed).toBe(3)
    expect(result.text).toBe('## 概述\n\n## 背景\n\n## 范围\n')
  })

  it('不动正文段落与列表序号', () => {
    const input = '## 项目基本信息\n\n1. 第一条\n2. 第二条\n\n一、正文里的序号\n'
    const result = stripHeadingNumbers(input)
    expect(result.changed).toBe(0)
    expect(result.text).toBe(input)
  })

  it('不动围栏代码块内的示例标题', () => {
    const input = '## 项目基本信息\n\n```\n## 一、代码里的示例标题\n```\n'
    const result = stripHeadingNumbers(input)
    expect(result.changed).toBe(0)
  })

  it('不动一级标题（文档标题）', () => {
    const input = '# 一、总体说明\n'
    expect(stripHeadingNumbers(input).changed).toBe(0)
  })

  it('未加空格的 ## 不是标题（与 Markdown 解析一致，不处理）', () => {
    const input = '##一、项目基本信息\n'
    expect(stripHeadingNumbers(input).changed).toBe(0)
  })

  it('整行只有序号时保留原标题', () => {
    const input = '## 一、\n'
    expect(stripHeadingNumbers(input).changed).toBe(0)
  })

  it('空正文安全', () => {
    expect(stripHeadingNumbers('')).toEqual({ text: '', changed: 0 })
  })

  it('hasHeadingNumbers 与 strip 口径一致', () => {
    expect(hasHeadingNumbers('## 一、背景\n')).toBe(true)
    expect(hasHeadingNumbers('## 背景\n')).toBe(false)
  })
})

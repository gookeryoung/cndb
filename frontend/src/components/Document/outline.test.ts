/**
 * 大纲与命中高亮纯函数测试 — parseOutline / headingAnchor / parseHitHighlight.
 */

import { describe, expect, it } from 'vitest'
import { headingAnchor, parseHitHighlight, parseOutline } from './outline'

describe('headingAnchor 锚点生成', () => {
  it('英文标题：小写 + 空格折叠为连字符', () => {
    expect(headingAnchor('Getting Started')).toBe('doc-h-getting-started')
  })

  it('中文标题保留（Unicode 字母不剔除）', () => {
    expect(headingAnchor('安装指南')).toBe('doc-h-安装指南')
  })

  it('特殊字符剔除、空文本回退 empty', () => {
    expect(headingAnchor('A/B: C!')).toBe('doc-h-ab-c')
    expect(headingAnchor('   ')).toBe('doc-h-empty')
  })
})

describe('parseOutline 大纲解析', () => {
  it('解析 ATX 标题层级与所在行，关闭尾随井号', () => {
    const md = '序言\n\n# 标题一\n\n## 子节 A ###\n\n正文\n\n### 三级 ###\n'
    const outline = parseOutline(md)
    expect(outline).toEqual([
      { level: 1, text: '标题一', anchor: 'doc-h-标题一', line: 2 },
      { level: 2, text: '子节 A', anchor: 'doc-h-子节-a', line: 4 },
      { level: 3, text: '三级', anchor: 'doc-h-三级', line: 8 },
    ])
  })

  it('代码围栏内的井号行不计入大纲', () => {
    const md = '# 真标题\n\n```\n# 注释标题\n## fake\n```\n\n## 围栏后'
    const outline = parseOutline(md)
    expect(outline.map(o => o.text)).toEqual(['真标题', '围栏后'])
  })

  it('井号后无空格不视为标题；无标题返回空数组', () => {
    expect(parseOutline('#no-space').map(o => o.text)).toEqual([])
    expect(parseOutline('普通段落\n正文')).toEqual([])
  })
})

describe('parseHitHighlight 命中高亮切片', () => {
  it('按 <mark> 标记切分：标记内高亮、其余普通文本', () => {
    expect(parseHitHighlight('前缀<mark>命中</mark>后缀')).toEqual([
      { text: '前缀', marked: false },
      { text: '命中', marked: true },
      { text: '后缀', marked: false },
    ])
  })

  it('无标记整段普通文本；空串返回空数组', () => {
    expect(parseHitHighlight('全部普通文本')).toEqual([{ text: '全部普通文本', marked: false }])
    expect(parseHitHighlight('')).toEqual([])
  })
})

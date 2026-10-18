/** wikilink 双链预处理纯函数测试 — 覆盖：基本转换 / 锚点与别名 / 围栏跳过 / 空标题保留 / href 解析往返 */

import { describe, expect, it } from 'vitest'
import {
  parseWikilinkHref,
  parseWikilinkInner,
  transformWikilinks,
  wikilinkLabel,
  WIKILINK_HREF_PREFIX,
} from './wikilink'

const href = (title: string) => `${WIKILINK_HREF_PREFIX}${encodeURIComponent(title)}`

describe('transformWikilinks', () => {
  it('基本转换：[[标题]] 替换为 Markdown 链接（href 编码）', () => {
    const out = transformWikilinks('参见 [[目标文档]] 节。')
    expect(out).toBe(`参见 [目标文档](${WIKILINK_HREF_PREFIX}${encodeURIComponent('目标文档')}) 节。`)
  })

  it('一行多个双链与标题首尾空格修剪', () => {
    const out = transformWikilinks('[[ A ]] 和 [[B]]')
    expect(out).toBe(`[A](${href('A')}) 和 [B](${href('B')})`)
  })

  it('别名：显示别名，跳转仍指向目标标题', () => {
    expect(transformWikilinks('见 [[目标文档|设计说明]]')).toBe(`见 [设计说明](${href('目标文档')})`)
  })

  it('锚点：无别名时显示「标题 › 锚点」，跳转指向目标标题', () => {
    expect(transformWikilinks('见 [[目标文档#第二章]]')).toBe(`见 [目标文档 › 第二章](${href('目标文档')})`)
  })

  it('锚点 + 别名：只显示别名', () => {
    expect(transformWikilinks('[[目标文档#第二章|二章]]')).toBe(`[二章](${href('目标文档')})`)
  })

  it('本文内锚点 [[#小节]] 退化为纯文本（无文档可跳）', () => {
    expect(transformWikilinks('先看 [[#小节]]')).toBe('先看 小节')
  })

  it('代码围栏内不转换', () => {
    const out = transformWikilinks('```\n[[字面保留]]\n```\n正文 [[真链接]]')
    expect(out).toContain('[[字面保留]]')
    expect(out).toContain(`[真链接](${WIKILINK_HREF_PREFIX}`)
  })

  it('空白标题按原文保留', () => {
    expect(transformWikilinks('空 [[ ]] 白')).toBe('空 [[ ]] 白')
  })

  it('无双链时原样返回', () => {
    expect(transformWikilinks('普通文本 [普通链接](https://x.com)')).toBe('普通文本 [普通链接](https://x.com)')
  })
})

describe('parseWikilinkInner / wikilinkLabel', () => {
  it('三段成分解析', () => {
    expect(parseWikilinkInner('目标#锚点|别名')).toEqual({ target: '目标', anchor: '锚点', alias: '别名' })
    expect(parseWikilinkInner('目标')).toEqual({ target: '目标', anchor: '', alias: '' })
    expect(parseWikilinkInner('#锚点')).toEqual({ target: '', anchor: '锚点', alias: '' })
    expect(parseWikilinkInner('目标|别名')).toEqual({ target: '目标', anchor: '', alias: '别名' })
  })

  it('展示文本优先级：别名 > 标题›锚点 > 标题', () => {
    expect(wikilinkLabel({ target: 'T', anchor: 'H', alias: 'A' })).toBe('A')
    expect(wikilinkLabel({ target: 'T', anchor: 'H', alias: '' })).toBe('T › H')
    expect(wikilinkLabel({ target: 'T', anchor: '', alias: '' })).toBe('T')
  })
})

describe('parseWikilinkHref', () => {
  it('往返：转换后的 href 解析回原标题', () => {
    expect(parseWikilinkHref(href('需求 说明'))).toBe('需求 说明')
  })

  it('非双链 href 返回 null', () => {
    expect(parseWikilinkHref('https://example.com')).toBeNull()
    expect(parseWikilinkHref('#普通锚点')).toBeNull()
    expect(parseWikilinkHref('')).toBeNull()
  })
})

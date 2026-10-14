/** wikilink 双链预处理纯函数测试 — 覆盖：基本转换 / 围栏跳过 / 空标题保留 / href 解析往返 */

import { describe, expect, it } from 'vitest'
import { parseWikilinkHref, transformWikilinks, WIKILINK_HREF_PREFIX } from './wikilink'

describe('transformWikilinks', () => {
  it('基本转换：[[标题]] 替换为 Markdown 链接（href 编码）', () => {
    const out = transformWikilinks('参见 [[目标文档]] 节。')
    expect(out).toBe(`参见 [目标文档](${WIKILINK_HREF_PREFIX}${encodeURIComponent('目标文档')}) 节。`)
  })

  it('一行多个双链与标题首尾空格修剪', () => {
    const out = transformWikilinks('[[ A ]] 和 [[B]]')
    expect(out).toBe(
      `[A](${WIKILINK_HREF_PREFIX}${encodeURIComponent('A')}) 和 [B](${WIKILINK_HREF_PREFIX}${encodeURIComponent('B')})`,
    )
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

describe('parseWikilinkHref', () => {
  it('往返：转换后的 href 解析回原标题', () => {
    const href = `${WIKILINK_HREF_PREFIX}${encodeURIComponent('需求 说明')}`
    expect(parseWikilinkHref(href)).toBe('需求 说明')
  })

  it('非双链 href 返回 null', () => {
    expect(parseWikilinkHref('https://example.com')).toBeNull()
    expect(parseWikilinkHref('#普通锚点')).toBeNull()
    expect(parseWikilinkHref('')).toBeNull()
  })
})

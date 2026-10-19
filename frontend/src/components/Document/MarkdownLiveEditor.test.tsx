/** MarkdownLiveEditor 实时预览 — 代码围栏的词法高亮与围栏行样式 */

import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import MarkdownLiveEditor from './MarkdownLiveEditor'

function renderEditor(value: string) {
  return render(
    <MarkdownLiveEditor value={value} mode="live" workspaceId={1} onChange={() => {}} />,
  )
}

describe('MarkdownLiveEditor 代码块高亮', () => {
  it('围栏代码块按语言着色，并区分围栏行与内容行', () => {
    const { container } = renderEditor('```ts\nconst n = 42\n```')
    expect(container.querySelector('.cn-tok-keyword')?.textContent).toBe('const')
    expect(container.querySelector('.cn-tok-number')?.textContent).toBe('42')
    // 围栏行淡色、内容行代码块底色
    expect(container.querySelectorAll('.cm-md-codefence').length).toBe(2)
    expect(container.querySelector('.cm-md-codeblock')).not.toBeNull()
  })

  it('未标注语言的围栏不高亮但仍套代码块样式', () => {
    const { container } = renderEditor('```\nplain text\n```')
    expect(container.querySelector('[class*="cn-tok-"]')).toBeNull()
    expect(container.querySelector('.cm-md-codeblock')).not.toBeNull()
  })

  it('源码模式仍为 textarea，不做装饰', () => {
    const { container } = render(
      <MarkdownLiveEditor value={'```ts\nconst a = 1\n```'} mode="source" onChange={() => {}} />,
    )
    expect(container.querySelector('textarea')).not.toBeNull()
    expect(container.querySelector('.cn-tok-keyword')).toBeNull()
  })
})

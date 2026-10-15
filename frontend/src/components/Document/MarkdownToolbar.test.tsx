/** MarkdownToolbar 组件测试 —— 按钮清单与 onAction 契约. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'
import MarkdownToolbar, { MARKDOWN_TOOLBAR_ITEMS } from './MarkdownToolbar'

describe('MarkdownToolbar', () => {
  it('渲染全部快捷按钮（含无障碍标签与 testid）', () => {
    renderProviders(<MarkdownToolbar onAction={() => { }} />)

    expect(screen.getByTestId('md-toolbar')).toBeInTheDocument()
    for (const item of MARKDOWN_TOOLBAR_ITEMS) {
      expect(screen.getByTestId(`md-toolbar-${item.key}`)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('加粗（Ctrl+B）')).toBeInTheDocument()
    expect(screen.getByLabelText('链接（Ctrl+K）')).toBeInTheDocument()
    expect(MARKDOWN_TOOLBAR_ITEMS.map(i => i.key)).toEqual([
      'bold', 'italic', 'code', 'heading', 'ul', 'ol', 'quote', 'codeblock', 'link',
    ])
  })

  it('点击按钮把对应纯函数交给 onAction（在选区上求值）', () => {
    const onAction = vi.fn()
    renderProviders(<MarkdownToolbar onAction={onAction} />)

    fireEvent.click(screen.getByTestId('md-toolbar-bold'))

    expect(onAction).toHaveBeenCalledTimes(1)
    const action = onAction.mock.calls[0]![0]
    expect(action('中文', 0, 2).value).toBe('**中文**')
  })

  it('disabled 时按钮不可点', () => {
    const onAction = vi.fn()
    renderProviders(<MarkdownToolbar onAction={onAction} disabled />)

    fireEvent.click(screen.getByTestId('md-toolbar-italic'))
    expect(onAction).not.toHaveBeenCalled()
  })
})

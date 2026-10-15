/** MarkdownToolbar 组件测试 —— 按钮清单与 onAction 契约. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'
import MarkdownToolbar, {
  MARKDOWN_HEADING_LEVELS,
  MARKDOWN_TABLE_PRESETS,
  MARKDOWN_TOOLBAR_ITEMS,
} from './MarkdownToolbar'

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
      'bold', 'italic', 'code', 'heading', 'ul', 'ol', 'quote', 'codeblock', 'table', 'link',
    ])
    expect(MARKDOWN_HEADING_LEVELS.map(l => l.label)).toEqual(['一级标题', '二级标题', '三级标题', '四级标题', '正文'])
    expect(MARKDOWN_TABLE_PRESETS.map(p => p.key)).toEqual(['2x2', '3x3', '4x4'])
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

  it('标题下拉：选择三级标题后 onAction 生成 ### 前缀', async () => {
    const onAction = vi.fn()
    renderProviders(<MarkdownToolbar onAction={onAction} />)

    fireEvent.click(screen.getByTestId('md-toolbar-heading'))
    fireEvent.click(await screen.findByText('三级标题'))

    expect(onAction).toHaveBeenCalledTimes(1)
    const action = onAction.mock.calls[0]![0]
    expect(action('标题', 0, 2).value).toBe('### 标题')
  })

  it('标题下拉：选择「正文」取消已有标题', async () => {
    const onAction = vi.fn()
    renderProviders(<MarkdownToolbar onAction={onAction} />)

    fireEvent.click(screen.getByTestId('md-toolbar-heading'))
    fireEvent.click(await screen.findByText('正文'))

    const action = onAction.mock.calls[0]![0]
    expect(action('# 标题', 0, 4).value).toBe('标题')
  })

  it('表格下拉：按预设调用 onInsertTable（列数 / 行数）', async () => {
    const onAction = vi.fn()
    const onInsertTable = vi.fn()
    renderProviders(<MarkdownToolbar onAction={onAction} onInsertTable={onInsertTable} />)

    fireEvent.click(screen.getByTestId('md-toolbar-table'))
    fireEvent.click(await screen.findByText('3 列 × 3 行'))

    expect(onInsertTable).toHaveBeenCalledWith(3, 3)
    expect(onAction).not.toHaveBeenCalled()
  })
})

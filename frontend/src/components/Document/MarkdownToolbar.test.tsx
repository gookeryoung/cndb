/** MarkdownToolbar 组件测试 —— 按钮清单与 onAction 契约. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'
import MarkdownToolbar, {
  MARKDOWN_AI_ITEMS,
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

  it('未传 onAiAction 时完全不渲染 AI 按钮（既有页面行为不变）', () => {
    renderProviders(<MarkdownToolbar onAction={() => { }} />)

    for (const item of MARKDOWN_AI_ITEMS) {
      expect(screen.queryByTestId(`md-toolbar-ai-${item.key}`)).toBeNull()
    }
  })

  it('传入 onAiAction 时渲染润色 / 精简 / 扩写三个入口', () => {
    renderProviders(<MarkdownToolbar onAction={() => { }} onAiAction={() => { }} />)

    expect(MARKDOWN_AI_ITEMS.map(i => i.key)).toEqual(['polish', 'shorten', 'expand'])
    for (const item of MARKDOWN_AI_ITEMS) {
      expect(screen.getByTestId(`md-toolbar-ai-${item.key}`)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('AI 润色选中文本')).toBeInTheDocument()
  })

  it('AI 入口点击回传指令，且 mousedown 阻止默认行为（不丢选区）', () => {
    const onAiAction = vi.fn()
    renderProviders(<MarkdownToolbar onAction={() => { }} onAiAction={onAiAction} />)

    const btn = screen.getByTestId('md-toolbar-ai-shorten')
    // fireEvent 返回 false 表示事件被 preventDefault —— 选区因此不会丢
    expect(fireEvent.mouseDown(btn)).toBe(false)
    fireEvent.click(btn)
    expect(onAiAction).toHaveBeenCalledWith('shorten')
  })

  it('aiDisabled 只禁用 AI 入口，普通 Markdown 按钮仍可用', () => {
    const onAiAction = vi.fn()
    const onAction = vi.fn()
    renderProviders(
      <MarkdownToolbar onAction={onAction} onAiAction={onAiAction} aiDisabled />,
    )

    expect(screen.getByTestId('md-toolbar-ai-polish')).toBeDisabled()
    expect(screen.getByTestId('md-toolbar-bold')).toBeEnabled()

    fireEvent.click(screen.getByTestId('md-toolbar-ai-polish'))
    expect(onAiAction).not.toHaveBeenCalled()
  })

  it('未传插入 props 时完全不渲染插入图片 / 插入表格引用按钮（既有调用方零感知）', () => {
    renderProviders(<MarkdownToolbar onAction={() => { }} />)

    expect(screen.queryByTestId('md-toolbar-image')).toBeNull()
    expect(screen.queryByTestId('md-toolbar-table-ref')).toBeNull()
    expect(screen.queryByLabelText('插入图片')).toBeNull()
    expect(screen.queryByLabelText('插入表格引用（数据表）')).toBeNull()
  })

  it('传入插入 props 时渲染两个入口，点击透传回调且不触发 onAction', () => {
    const onAction = vi.fn()
    const onInsertImage = vi.fn()
    const onInsertTableRef = vi.fn()
    renderProviders(
      <MarkdownToolbar
        onAction={onAction}
        onInsertImage={onInsertImage}
        onInsertTableRef={onInsertTableRef}
      />,
    )

    // 与既有 table（Markdown 表格骨架）并存且可区分
    expect(screen.getByTestId('md-toolbar-table')).toBeInTheDocument()
    expect(screen.getByTestId('md-toolbar-table-ref')).toBeInTheDocument()
    expect(screen.getByLabelText('插入图片')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('md-toolbar-image'))
    fireEvent.click(screen.getByTestId('md-toolbar-table-ref'))
    expect(onInsertImage).toHaveBeenCalledTimes(1)
    expect(onInsertTableRef).toHaveBeenCalledTimes(1)
    expect(onAction).not.toHaveBeenCalled()
  })

  it('imageInsertLoading 只禁用插入图片按钮，插入表格引用与普通按钮仍可用', () => {
    const onInsertImage = vi.fn()
    const onInsertTableRef = vi.fn()
    const onAction = vi.fn()
    renderProviders(
      <MarkdownToolbar
        onAction={onAction}
        onInsertImage={onInsertImage}
        imageInsertLoading
        onInsertTableRef={onInsertTableRef}
      />,
    )

    expect(screen.getByTestId('md-toolbar-image')).toBeDisabled()
    expect(screen.getByTestId('md-toolbar-table-ref')).toBeEnabled()
    expect(screen.getByTestId('md-toolbar-bold')).toBeEnabled()

    fireEvent.click(screen.getByTestId('md-toolbar-image'))
    expect(onInsertImage).not.toHaveBeenCalled()
  })

  it('未传 onInsertChart 时不渲染插入图表按钮（ADR 0048）', () => {
    renderProviders(<MarkdownToolbar onAction={() => { }} />)

    expect(screen.queryByTestId('md-toolbar-chart')).toBeNull()
    expect(screen.queryByLabelText('插入图表')).toBeNull()
  })

  it('传入 onInsertChart 时渲染按钮，点击透传回调且与表格引用并存（ADR 0048）', () => {
    const onInsertChart = vi.fn()
    renderProviders(
      <MarkdownToolbar onAction={() => { }} onInsertTableRef={() => { }} onInsertChart={onInsertChart} />,
    )

    expect(screen.getByTestId('md-toolbar-chart')).toBeInTheDocument()
    expect(screen.getByTestId('md-toolbar-table-ref')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('md-toolbar-chart'))
    expect(onInsertChart).toHaveBeenCalledTimes(1)
  })
})

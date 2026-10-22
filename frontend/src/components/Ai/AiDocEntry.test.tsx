/** AiDocEntry 单测 —— 顶栏 AI 下拉入口（摘要 / 标签建议）与禁用态（ADR 0020 P1） */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import AiDocEntry from './AiDocEntry'

describe('AiDocEntry', () => {
  it('下拉菜单包含摘要 / 标签建议，点击分别触发回调', async () => {
    const onSummarize = vi.fn()
    const onSuggestTags = vi.fn()
    render(<AiDocEntry onSummarize={onSummarize} onSuggestTags={onSuggestTags} />)

    fireEvent.click(screen.getByTestId('doc-ai-entry'))
    fireEvent.click(await screen.findByText('AI 摘要'))
    expect(onSummarize).toHaveBeenCalledTimes(1)
    expect(onSuggestTags).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('doc-ai-entry'))
    fireEvent.click(await screen.findByText('AI 标签建议'))
    expect(onSuggestTags).toHaveBeenCalledTimes(1)
  })

  it('disabled 时不展开菜单', async () => {
    const onSummarize = vi.fn()
    render(<AiDocEntry disabled onSummarize={onSummarize} onSuggestTags={() => {}} />)

    fireEvent.click(screen.getByTestId('doc-ai-entry'))
    // 菜单不出现（antd Dropdown disabled 直接忽略点击）
    expect(screen.queryByText('AI 摘要')).toBeNull()
  })
})

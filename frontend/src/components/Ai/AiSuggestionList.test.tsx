/** AiSuggestionList 单测 —— 建议 chips 展示 / 多选切换 / 空态（ADR 0020 P1） */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import AiSuggestionList from './AiSuggestionList'

describe('AiSuggestionList', () => {
  it('只读模式：逐项渲染 chips，点击不触发 onChange', () => {
    const onChange = vi.fn()
    render(<AiSuggestionList items={['流程优化', '审批效率']} testId="tags" />)

    expect(screen.getByTestId('tags')).toBeInTheDocument()
    expect(screen.getByTestId('tags-item-流程优化')).toHaveTextContent('流程优化')
    fireEvent.click(screen.getByTestId('tags-item-审批效率'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('多选模式：点击追加 / 再点移除，回传完整选中列表', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <AiSuggestionList items={['流程优化', '审批效率']} selected={[]} onChange={onChange} testId="tags" />,
    )

    fireEvent.click(screen.getByTestId('tags-item-流程优化'))
    expect(onChange).toHaveBeenLastCalledWith(['流程优化'])

    rerender(
      <AiSuggestionList
        items={['流程优化', '审批效率']}
        selected={['流程优化']}
        onChange={onChange}
        testId="tags"
      />,
    )
    fireEvent.click(screen.getByTestId('tags-item-审批效率'))
    expect(onChange).toHaveBeenLastCalledWith(['流程优化', '审批效率'])

    rerender(
      <AiSuggestionList
        items={['流程优化', '审批效率']}
        selected={['流程优化', '审批效率']}
        onChange={onChange}
        testId="tags"
      />,
    )
    fireEvent.click(screen.getByTestId('tags-item-流程优化'))
    expect(onChange).toHaveBeenLastCalledWith(['审批效率'])
  })

  it('空列表展示空态文案', () => {
    render(<AiSuggestionList items={[]} emptyText="模型未给出标签建议" />)
    expect(screen.getByText('模型未给出标签建议')).toBeInTheDocument()
  })
})

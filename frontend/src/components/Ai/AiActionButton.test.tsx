/** AiActionButton 单测 —— 文案 / 图标 / loading 与 disabled 行为（ADR 0020 P1） */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { RobotOutlined } from '@ant-design/icons'

import AiActionButton from './AiActionButton'

describe('AiActionButton', () => {
  it('渲染文案、图标与 testid，点击触发回调', () => {
    const onClick = vi.fn()
    render(
      <AiActionButton
        icon={<RobotOutlined data-testid="ai-icon" />}
        label="AI 摘要"
        tooltip="整篇摘要"
        testId="ai-btn"
        onClick={onClick}
      />,
    )

    const button = screen.getByTestId('ai-btn')
    expect(button).toHaveTextContent('AI 摘要')
    expect(screen.getByTestId('ai-icon')).toBeInTheDocument()

    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('disabled / loading 时不可点击', () => {
    const onClick = vi.fn()
    const { rerender } = render(<AiActionButton label="AI" testId="ai-btn" disabled onClick={onClick} />)
    expect(screen.getByTestId('ai-btn')).toBeDisabled()
    fireEvent.click(screen.getByTestId('ai-btn'))
    expect(onClick).not.toHaveBeenCalled()

    rerender(<AiActionButton label="AI" testId="ai-btn" loading onClick={onClick} />)
    // antd 的 loading 态不写 disabled 属性，而是拦截点击（带 ant-btn-loading 类）
    expect(screen.getByTestId('ai-btn')).toHaveClass('ant-btn-loading')
    fireEvent.click(screen.getByTestId('ai-btn'))
    expect(onClick).not.toHaveBeenCalled()
  })
})

/** ErrorBoundary 单元测试 —— fallback 渲染、重试恢复、错误上报钩子 */
import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ErrorBoundary from './ErrorBoundary'

function Bomb({ crash }: { crash: boolean }) {
  if (crash) throw new Error('boom')
  return <div>ok</div>
}

afterEach(cleanup)

describe('ErrorBoundary', () => {
  it('子组件正常时直接渲染，不显示 fallback', () => {
    render(<ErrorBoundary><Bomb crash={false} /></ErrorBoundary>)
    expect(screen.getByText('ok')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('子组件崩溃时展示降级 UI 与错误信息', () => {
    render(<ErrorBoundary><Bomb crash /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('页面出现异常')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('重试按钮清除错误状态并重挂 children', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<ErrorBoundary><Bomb crash /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toBeInTheDocument()

    // 先移除崩溃源，再点重试 —— 模拟「错误条件已修复后恢复」
    rerender(<ErrorBoundary><Bomb crash={false} /></ErrorBoundary>)
    await user.click(screen.getByRole('button', { name: /重试/ }))
    expect(screen.getByText('ok')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('onError 接收错误与组件栈（错误上报接入点）', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ErrorBoundary><Bomb crash /></ErrorBoundary>)
    expect(consoleSpy).toHaveBeenCalledWith(
      '[ErrorBoundary]',
      expect.any(Error),
      expect.any(String),
    )
  })
})

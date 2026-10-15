/** FindReplaceBar 组件测试 —— 计数展示与回调契约. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'
import FindReplaceBar from './FindReplaceBar'

function setup(overrides: Partial<React.ComponentProps<typeof FindReplaceBar>> = {}) {
  const props = {
    query: 'foo',
    replacement: 'bar',
    matches: [{ start: 0, end: 3 }, { start: 8, end: 11 }],
    currentIndex: 0,
    caseSensitive: false,
    onQueryChange: vi.fn(),
    onReplacementChange: vi.fn(),
    onPrev: vi.fn(),
    onNext: vi.fn(),
    onReplace: vi.fn(),
    onReplaceAll: vi.fn(),
    onToggleCase: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  }
  renderProviders(<FindReplaceBar {...props} />)
  return props
}

describe('FindReplaceBar', () => {
  it('展示「第几处 / 共几处」计数', () => {
    setup({ currentIndex: 1 })
    expect(screen.getByTestId('doc-find-count')).toHaveTextContent('2/2')
  })

  it('未定位时计数显示第 1 处', () => {
    setup({ currentIndex: -1 })
    expect(screen.getByTestId('doc-find-count')).toHaveTextContent('1/2')
  })

  it('无匹配时提示无结果', () => {
    setup({ matches: [], currentIndex: -1 })
    expect(screen.getByTestId('doc-find-count')).toHaveTextContent('无结果')
  })

  it('输入查询 / 替换文本触发回调', () => {
    const props = setup()
    fireEvent.change(screen.getByTestId('doc-find-input'), { target: { value: 'next' } })
    fireEvent.change(screen.getByTestId('doc-find-replacement'), { target: { value: 'repl' } })

    expect(props.onQueryChange).toHaveBeenCalledWith('next')
    expect(props.onReplacementChange).toHaveBeenCalledWith('repl')
  })

  it('上一个 / 下一个 / 替换 / 全部替换 / 大小写 / 关闭均可触发；无匹配时导航禁用', () => {
    const props = setup()
    fireEvent.click(screen.getByTestId('doc-find-next'))
    fireEvent.click(screen.getByTestId('doc-find-prev'))
    fireEvent.click(screen.getByTestId('doc-find-replace'))
    fireEvent.click(screen.getByTestId('doc-find-replace-all'))
    fireEvent.click(screen.getByTestId('doc-find-case'))
    fireEvent.click(screen.getByTestId('doc-find-close'))

    expect(props.onNext).toHaveBeenCalledTimes(1)
    expect(props.onPrev).toHaveBeenCalledTimes(1)
    expect(props.onReplace).toHaveBeenCalledTimes(1)
    expect(props.onReplaceAll).toHaveBeenCalledTimes(1)
    expect(props.onToggleCase).toHaveBeenCalledTimes(1)
    expect(props.onClose).toHaveBeenCalledTimes(1)
  })

  it('无匹配时导航与替换按钮禁用', () => {
    setup({ matches: [] })
    expect(screen.getByTestId('doc-find-next')).toBeDisabled()
    expect(screen.getByTestId('doc-find-prev')).toBeDisabled()
    expect(screen.getByTestId('doc-find-replace')).toBeDisabled()
    expect(screen.getByTestId('doc-find-replace-all')).toBeDisabled()
  })

  it('查找框回车=下一个，Shift+回车=上一个', () => {
    const props = setup()
    fireEvent.keyDown(screen.getByTestId('doc-find-input'), { key: 'Enter' })
    fireEvent.keyDown(screen.getByTestId('doc-find-input'), { key: 'Enter', shiftKey: true })

    expect(props.onNext).toHaveBeenCalledTimes(1)
    expect(props.onPrev).toHaveBeenCalledTimes(1)
  })
})

/** PPTX 全屏放映：初始化 slide 模式、键盘翻页、退出. */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import PptxSlideshow from './PptxSlideshow'

const state = vi.hoisted(() => ({
  slideCount: 3,
  renderSingleSlide: vi.fn(),
  preview: vi.fn(),
  destroy: vi.fn(),
  init: vi.fn(),
}))

vi.mock('pptx-preview', () => ({ init: state.init }))

const BLOB = new Blob(['PK'], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })

beforeEach(() => {
  state.slideCount = 3
  state.renderSingleSlide.mockClear()
  state.preview.mockReset().mockResolvedValue({})
  state.destroy.mockClear()
  state.init.mockReset().mockImplementation(() => ({
    preview: state.preview,
    destroy: state.destroy,
    renderSingleSlide: state.renderSingleSlide,
    get slideCount() { return state.slideCount },
  }))
})

describe('PptxSlideshow', () => {
  it('以 slide 模式初始化并显示总页数', async () => {
    render(<PptxSlideshow blob={BLOB} title="胶片" onClose={() => { }} />)

    await waitFor(() => expect(state.init).toHaveBeenCalled())
    const [, options] = state.init.mock.calls[0] as unknown as [HTMLElement, Record<string, unknown>]
    expect(options.mode).toBe('slide')
    expect(await screen.findByTestId('doc-pptx-slide-index')).toHaveTextContent('1 / 3')
    expect(screen.getByTestId('doc-asset-pptx-slideshow')).toBeInTheDocument()
  })

  it('键盘 / 按钮翻页并在边界禁用', async () => {
    render(<PptxSlideshow blob={BLOB} title="胶片" onClose={() => { }} />)
    await screen.findByTestId('doc-pptx-slide-index')

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(state.renderSingleSlide).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByTestId('doc-pptx-slide-index')).toHaveTextContent('2 / 3'))
    expect(state.renderSingleSlide).toHaveBeenLastCalledWith(1)

    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByTestId('doc-pptx-slide-index')).toHaveTextContent('3 / 3'))
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()

    fireEvent.keyDown(window, { key: 'PageUp' })
    await waitFor(() => expect(screen.getByTestId('doc-pptx-slide-index')).toHaveTextContent('2 / 3'))
    expect(screen.getByRole('button', { name: '上一页' })).toBeEnabled()
  })

  it('Esc 与退出按钮都会关闭放映', async () => {
    const onClose = vi.fn()
    const { rerender } = render(<PptxSlideshow blob={BLOB} title="胶片" onClose={onClose} />)
    await screen.findByTestId('doc-pptx-slide-index')

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)

    rerender(<PptxSlideshow blob={BLOB} title="胶片" onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: '退出放映' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('渲染失败给出可退出提示', async () => {
    state.preview.mockRejectedValue(new Error('bad zip'))
    render(<PptxSlideshow blob={BLOB} title="胶片" onClose={() => { }} />)

    expect(await screen.findByText(/无法放映/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出放映' })).toBeEnabled()
  })
})

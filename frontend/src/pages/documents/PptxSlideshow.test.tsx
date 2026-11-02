/** PPTX 全屏放映：初始化 slide 模式、键盘翻页、退出. */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StrictMode } from 'react'
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

  it('点击左侧 / 右侧区域分别上一页 / 下一页', async () => {
    render(<PptxSlideshow blob={BLOB} title="胶片" onClose={() => { }} />)
    await screen.findByTestId('doc-pptx-slide-index')

    // 首屏左侧已禁用，右侧可点 → 第二页
    expect(screen.getByRole('button', { name: '点击左侧上一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '点击右侧下一页' }))
    await waitFor(() => expect(screen.getByTestId('doc-pptx-slide-index')).toHaveTextContent('2 / 3'))

    // 右侧继续 → 末页后禁用
    fireEvent.click(screen.getByRole('button', { name: '点击右侧下一页' }))
    await waitFor(() => expect(screen.getByTestId('doc-pptx-slide-index')).toHaveTextContent('3 / 3'))
    expect(screen.getByRole('button', { name: '点击右侧下一页' })).toBeDisabled()

    // 左侧可点 → 后退
    fireEvent.click(screen.getByRole('button', { name: '点击左侧上一页' }))
    await waitFor(() => expect(screen.getByTestId('doc-pptx-slide-index')).toHaveTextContent('2 / 3'))
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

  it('StrictMode 双执行不会「刚进全屏就退出」；浏览器退出全屏才关闭', async () => {
    const onClose = vi.fn()
    let fullscreenEl: Element | null = null
    const originalRequest = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'requestFullscreen')
    const originalExit = Object.getOwnPropertyDescriptor(document, 'exitFullscreen')
    const originalCurrent = Object.getOwnPropertyDescriptor(document, 'fullscreenElement')

    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => fullscreenEl })
    Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
      configurable: true,
      value: () => {
        fullscreenEl = document.querySelector('[data-testid="doc-asset-pptx-slideshow"]')
        document.dispatchEvent(new Event('fullscreenchange'))
        return Promise.resolve()
      },
    })
    Object.defineProperty(document, 'exitFullscreen', {
      configurable: true,
      value: () => {
        fullscreenEl = null
        document.dispatchEvent(new Event('fullscreenchange'))
        return Promise.resolve()
      },
    })

    try {
      render(
        <StrictMode>
          <PptxSlideshow blob={BLOB} title="胶片" onClose={onClose} />
        </StrictMode>,
      )
      await screen.findByTestId('doc-pptx-slide-index')
      // StrictMode 的 effect 清理 / 二次挂载不得触发退出
      expect(onClose).not.toHaveBeenCalled()

      // 用户通过浏览器 Esc 退出全屏 → 关闭覆盖层
      fullscreenEl = null
      document.dispatchEvent(new Event('fullscreenchange'))
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    } finally {
      if (originalRequest) Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', originalRequest)
      else delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen
      if (originalExit) Object.defineProperty(document, 'exitFullscreen', originalExit)
      else delete (document as { exitFullscreen?: unknown }).exitFullscreen
      if (originalCurrent) Object.defineProperty(document, 'fullscreenElement', originalCurrent)
    }
  })

  it('渲染失败给出可退出提示', async () => {
    state.preview.mockRejectedValue(new Error('bad zip'))
    render(<PptxSlideshow blob={BLOB} title="胶片" onClose={() => { }} />)

    expect(await screen.findByText(/无法放映/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出放映' })).toBeEnabled()
  })
})

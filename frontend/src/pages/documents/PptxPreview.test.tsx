/** PPTX 在线预览组件：逐页渲染、翻页控制、失败兜底与共享加载器. */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import PptxPreview from './PptxPreview'
import { loadPptxModule } from './pptxLoader'

const pptx = vi.hoisted(() => {
  const state = {
    slideCount: 3,
    preview: vi.fn(),
    destroy: vi.fn(),
    renderSingleSlide: vi.fn(),
    init: vi.fn(),
  }
  return state
})

vi.mock('pptx-preview', () => ({ init: pptx.init }))

const BLOB = new Blob(['PK'], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })

async function waitReady(pageText = '1 / 3') {
  await waitFor(() => expect(screen.getByTestId('doc-pptx-preview-index')).toHaveTextContent(pageText))
}

beforeEach(() => {
  pptx.slideCount = 3
  pptx.renderSingleSlide.mockClear()
  pptx.preview.mockReset().mockResolvedValue({})
  pptx.destroy.mockClear()
  pptx.init.mockReset().mockImplementation(() => ({
    preview: pptx.preview,
    destroy: pptx.destroy,
    renderSingleSlide: pptx.renderSingleSlide,
    get slideCount() { return pptx.slideCount },
  }))
})

describe('PptxPreview', () => {
  it('按容器宽度初始化 slide 模式并只渲染当前页', async () => {
    render(<PptxPreview blob={BLOB} title="胶片" />)

    await waitFor(() => expect(pptx.init).toHaveBeenCalled())
    const [host, options] = pptx.init.mock.calls[0] as unknown as [HTMLElement, Record<string, unknown>]
    expect(host).toBeInstanceOf(HTMLElement)
    // jsdom clientWidth / clientHeight=0 → 宽度回落 960，高度按 4:3 兜底 720
    expect(options).toEqual({ width: 960, height: 720, mode: 'slide' })
    await waitReady()
    expect((pptx.preview.mock.calls[0] as unknown[])[0]).toBeInstanceOf(ArrayBuffer)
    expect(screen.getByTestId('doc-asset-pptx')).toBeInTheDocument()
    // slide 模式不会一次性渲染全部页
    expect(pptx.renderSingleSlide).not.toHaveBeenCalled()
  })

  it('上一页 / 下一页逐页切换并在边界禁用', async () => {
    render(<PptxPreview blob={BLOB} title="胶片" />)
    await waitReady()

    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(pptx.renderSingleSlide).toHaveBeenLastCalledWith(1)
    await waitReady('2 / 3')

    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(pptx.renderSingleSlide).toHaveBeenLastCalledWith(2)
    await waitReady('3 / 3')
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '上一页' }))
    expect(pptx.renderSingleSlide).toHaveBeenLastCalledWith(1)
    await waitReady('2 / 3')
  })

  it('渲染失败显示下载提示而不是空白', async () => {
    pptx.preview.mockRejectedValue(new Error('bad zip'))
    render(<PptxPreview blob={BLOB} title="损坏胶片" />)

    expect(await screen.findByTestId('doc-asset-pptx-error')).toBeInTheDocument()
    expect(screen.getByText(/「损坏胶片」无法在线渲染/)).toBeInTheDocument()
  })

  it('卸载时销毁渲染器', async () => {
    const { unmount } = render(<PptxPreview blob={BLOB} title="胶片" />)
    await waitReady()
    unmount()
    expect(pptx.destroy).toHaveBeenCalled()
  })
})

describe('pptxLoader', () => {
  it('同一会话复用同一个动态 import Promise', async () => {
    const first = loadPptxModule()
    const second = loadPptxModule()
    expect(second).toBe(first)
    await expect(first).resolves.toBeTruthy()
  })
})

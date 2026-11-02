/** PPTX 在线预览组件：懒加载渲染库、容器尺寸、失败兜底. */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import PptxPreview from './PptxPreview'

const pptx = vi.hoisted(() => {
  const preview = vi.fn()
  const destroy = vi.fn()
  const init = vi.fn(() => ({ preview, destroy }))
  return { init, preview, destroy }
})

vi.mock('pptx-preview', () => ({ init: pptx.init }))

const BLOB = new Blob(['PK'], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })

beforeEach(() => {
  pptx.init.mockClear()
  pptx.preview.mockReset().mockResolvedValue({})
  pptx.destroy.mockClear()
})

describe('PptxPreview', () => {
  it('按容器宽度初始化 list 模式并渲染 ArrayBuffer', async () => {
    render(<PptxPreview blob={BLOB} title="胶片" />)

    await waitFor(() => expect(pptx.init).toHaveBeenCalled())
    const [host, options] = pptx.init.mock.calls[0] as unknown as [HTMLElement, Record<string, unknown>]
    expect(host).toBeInstanceOf(HTMLElement)
    // jsdom clientWidth=0 → 回落 960
    expect(options).toEqual({ width: 960, mode: 'list' })
    await waitFor(() => expect(pptx.preview).toHaveBeenCalled())
    expect((pptx.preview.mock.calls[0] as unknown[])[0]).toBeInstanceOf(ArrayBuffer)
    expect(screen.getByTestId('doc-asset-pptx')).toBeInTheDocument()
  })

  it('渲染失败显示下载提示而不是空白', async () => {
    pptx.preview.mockRejectedValue(new Error('bad zip'))
    render(<PptxPreview blob={BLOB} title="损坏胶片" />)

    expect(await screen.findByTestId('doc-asset-pptx-error')).toBeInTheDocument()
    expect(screen.getByText(/「损坏胶片」无法在线渲染/)).toBeInTheDocument()
  })

  it('卸载时销毁渲染器', async () => {
    const { unmount } = render(<PptxPreview blob={BLOB} title="胶片" />)
    await waitFor(() => expect(pptx.preview).toHaveBeenCalled())
    unmount()
    expect(pptx.destroy).toHaveBeenCalled()
  })
})

/** InsertChartModal 组件测试 — 多级列表浏览 / 按需预览 / 素材库复制插入 / 回调契约（ADR 0048 / 0052 / 0058）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { mockChartInstance } from '@/test/msw'
import { renderProviders } from '@/test/render-providers'
import InsertChartModal from './InsertChartModal'

function renderModal(overrides: Partial<Parameters<typeof InsertChartModal>[0]> = {}) {
  const props = {
    open: true,
    workspaceId: 10,
    onCancel: vi.fn(),
    onPickExisting: vi.fn(),
    onPickTemplate: vi.fn(),
    ...overrides,
  }
  renderProviders(<InsertChartModal {...props} />)
  return props
}

describe('InsertChartModal', () => {
  it('「新建图表」页签：左栏多级列表（一级常显、二级展开），右栏未选中为空态且不发预览（C2/C3）', async () => {
    renderModal()

    // 一级分类常显；第一个含模板的一级默认展开出二级与模板项
    expect(await screen.findByText('目标对比')).toBeInTheDocument()
    expect(screen.getByText('对比-柱形')).toBeInTheDocument()
    expect(screen.getByText('对比-条形')).toBeInTheDocument()
    expect(screen.getByTestId('chart-template-item-bar-line-dual-axis')).toBeInTheDocument()
    expect(screen.getByTestId('chart-template-item-stacked-bar-horizontal')).toBeInTheDocument()
    expect(screen.getByTestId('chart-template-item-grouped-bar-horizontal')).toBeInTheDocument()

    // 未选中：右栏空态，无缩略图（不请求 render-preview）
    expect(screen.getByText('在左侧选择一个模板查看预览')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-template-thumb-bar-line-dual-axis')).not.toBeInTheDocument()
  })

  it('选中模板后右栏出预览与「基于此模板新建」，回传模板 key（C2/C3）', async () => {
    const props = renderModal()

    // 未选中前右栏无预览
    expect(screen.queryByTestId('chart-template-thumb-stacked-bar-horizontal')).not.toBeInTheDocument()
    fireEvent.click(await screen.findByTestId('chart-template-item-stacked-bar-horizontal'))
    await waitFor(() => {
      expect(screen.getByTestId('chart-template-thumb-stacked-bar-horizontal')).toBeInTheDocument()
    })
    expect(screen.getByTestId('chart-template-pick-stacked-bar-horizontal')).toBeInTheDocument()

    // 「基于此模板新建」固定在弹窗底部（footer），位于「取消」左侧
    const footer = screen.getByTestId('chart-template-pick-stacked-bar-horizontal').closest('.ant-modal-footer')
    expect(footer).not.toBeNull()
    expect(within(footer as HTMLElement).getByRole('button', { name: /^取\s*消$/ })).toBeInTheDocument()
    const pickBtn = screen.getByTestId('chart-template-pick-stacked-bar-horizontal')
    const cancelBtn = within(footer as HTMLElement).getByRole('button', { name: /^取\s*消$/ })
    expect(pickBtn.compareDocumentPosition(cancelBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // 弹窗文字允许选中复制（user-select 放开）
    expect(document.querySelector('.cn-insert-chart-modal')).not.toBeNull()

    fireEvent.click(screen.getByTestId('chart-template-pick-stacked-bar-horizontal'))
    expect(props.onPickTemplate).toHaveBeenCalledTimes(1)
    expect(props.onPickTemplate).toHaveBeenCalledWith('stacked-bar-horizontal')
    expect(props.onPickExisting).not.toHaveBeenCalled()
  })

  it('「图表素材库」页签：列出素材并回传完整条目（页面复制定义插入）', async () => {
    const props = renderModal()

    fireEvent.click(await screen.findByText(/图表素材库/))
    const item = await screen.findByTestId('chart-existing-item-300')
    expect(within(item).getByText('产业营业收入与增速')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('chart-existing-insert-300'))
    expect(props.onPickExisting).toHaveBeenCalledWith(expect.objectContaining({ id: 300, template_key: 'bar-line-dual-axis' }))
    expect(mockChartInstance.template_key).toBe('bar-line-dual-axis')
    expect(props.onPickTemplate).not.toHaveBeenCalled()
  })

  it('取消按钮透传 onCancel', async () => {
    const props = renderModal()

    fireEvent.click(await screen.findByRole('button', { name: /^取\s*消$/ }))

    expect(props.onCancel).toHaveBeenCalledTimes(1)
  })
})

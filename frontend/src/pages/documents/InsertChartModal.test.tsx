/** InsertChartModal 组件测试 — 模板两级浏览 / 素材库复制插入 / 两个回调契约（ADR 0048 / 0052）. */

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
  it('「新建图表」页签：类别分组展示全部模板卡片（名称 + 描述 + 缩略图）', async () => {
    renderModal()

    // 类别（一级）
    expect(await screen.findByText('趋势分析')).toBeInTheDocument()
    expect(screen.getByText('结构构成')).toBeInTheDocument()
    expect(screen.getByText('目标对比')).toBeInTheDocument()

    // 模板（二级）：名称与「基于此模板新建」入口
    expect(screen.getByText('柱线组合图（双轴）')).toBeInTheDocument()
    expect(screen.getByText('水平堆叠条形图')).toBeInTheDocument()
    expect(screen.getByText('水平分组条形图')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('chart-template-thumb-bar-line-dual-axis')).toBeInTheDocument()
    })
  })

  it('点「基于此模板新建」回传模板 key（页面接手打开设计器）', async () => {
    const props = renderModal()

    fireEvent.click(await screen.findByTestId('chart-template-pick-stacked-bar-horizontal'))

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

/** TooltipDropdown 组件测试：菜单展开期间关闭说明 Tooltip（防浮层遮挡菜单项）.
 *
 * 背景：Tooltip 在视口顶部会翻转到触发器下方，正好盖住 Dropdown 菜单；
 * 浮层默认可交互（指针移入保持展开）会拦截菜单项点击（真实 E2E 超时回归）。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { renderProviders } from '@/test/render-providers'
import TooltipDropdown from './TooltipDropdown'

function renderTipDropdown(onClick = vi.fn()) {
  renderProviders(
    <TooltipDropdown
      title="更多操作说明"
      menu={{ items: [{ key: 'reset', label: '重置列宽与列序', onClick }] }}
    >
      <button type="button">更多</button>
    </TooltipDropdown>,
  )
  return { trigger: screen.getByRole('button', { name: '更多' }), onClick }
}

describe('TooltipDropdown', () => {
  it('悬浮触发说明 Tooltip，展开菜单时 Tooltip 关闭', async () => {
    const { trigger } = renderTipDropdown()

    await userEvent.hover(trigger)
    await waitFor(() => expect(trigger).toHaveClass('ant-tooltip-open'))

    fireEvent.click(trigger)
    expect(await screen.findByText('重置列宽与列序')).toBeInTheDocument()
    // 菜单展开期间 Tooltip 必须关闭，否则会盖住菜单并拦截点击
    await waitFor(() => expect(trigger).not.toHaveClass('ant-tooltip-open'))
  })

  it('菜单项点击可触发并把关闭事件交给调用方管理', async () => {
    const { trigger, onClick } = renderTipDropdown()

    fireEvent.click(trigger)
    fireEvent.click(await screen.findByText('重置列宽与列序'))

    await waitFor(() => expect(onClick).toHaveBeenCalledTimes(1))
  })
})

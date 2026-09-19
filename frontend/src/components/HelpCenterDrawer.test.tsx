/** HelpCenterDrawer 测试：打开渲染、主题切换、重放按钮触发信号. */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HelpCenterDrawer from './HelpCenterDrawer'
import { useOnboardingStore } from '@/store/onboarding'
import { renderProviders } from '@/test/render-providers'

function renderDrawer(open = true) {
  return renderProviders(<HelpCenterDrawer open={open} onClose={() => { }} />)
}

describe('HelpCenterDrawer', () => {
  beforeEach(() => {
    useOnboardingStore.setState({ tourDone: false, tourRequested: false })
  })

  it('打开时展示帮助中心标题与默认主题（快速上手）', () => {
    renderDrawer()
    expect(screen.getByText('帮助中心')).toBeInTheDocument()
    expect(screen.getByText('创建工作区')).toBeInTheDocument()
  })

  it('open=false 时不渲染内容', () => {
    renderDrawer(false)
    expect(screen.queryByText('帮助中心')).not.toBeInTheDocument()
  })

  it('点击左侧主题切换内容区', async () => {
    renderDrawer()
    await userEvent.click(screen.getByText('常见问题'))
    expect(await screen.findByText('筛选和排序会保存吗？')).toBeInTheDocument()
  })

  it('六大主题菜单齐全', () => {
    renderDrawer()
    for (const label of ['快速上手', '视图类型说明', '数据导入导出', '权限与角色', '字段类型参考', '常见问题']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('「重新播放新手引导」按钮发出 requestTour 信号并支持关闭', async () => {
    const onClose = vi.fn()
    renderProviders(<HelpCenterDrawer open onClose={onClose} />)
    await userEvent.click(screen.getByTestId('replay-tour-btn'))
    expect(useOnboardingStore.getState().tourRequested).toBe(true)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

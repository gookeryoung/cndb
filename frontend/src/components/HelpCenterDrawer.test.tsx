/** HelpCenterDrawer 测试：打开渲染、主题切换、重放按钮触发信号. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HelpCenterDrawer from './HelpCenterDrawer'
import { useOnboardingStore } from '@/store/onboarding'
import { renderProviders } from '@/test/render-providers'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端，移动端用例在其内部切换
let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

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
    // 标题为编号格式「1. 创建工作区」，用正则匹配避免精确文本失配
    expect(screen.getByText(/创建工作区/)).toBeInTheDocument()
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

describe('HelpCenterDrawer 移动端主题导航', () => {
  beforeEach(() => {
    useOnboardingStore.setState({ tourDone: false, tourRequested: false })
  })

  afterEach(() => {
    responsiveState = {
      deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
      width: 1280, height: 800,
    }
  })

  it('窄屏下改为顶部横向胶囊导航（无左侧竖排菜单），点击可切换主题', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    renderDrawer()

    expect(document.querySelector('.ant-menu-inline')).toBeNull()
    expect(document.querySelectorAll('.cn-help-topic')).toHaveLength(6)
    expect(document.querySelector('.cn-help-topic-active')).toHaveTextContent('快速上手')

    await userEvent.click(screen.getByText('常见问题'))
    expect(await screen.findByText('筛选和排序会保存吗？')).toBeInTheDocument()
    expect(document.querySelector('.cn-help-topic-active')).toHaveTextContent('常见问题')
  })

  it('桌面端保持左侧竖排菜单，不渲染胶囊导航', () => {
    renderDrawer()
    expect(document.querySelector('.ant-menu-inline')).toBeTruthy()
    expect(document.querySelectorAll('.cn-help-topic')).toHaveLength(0)
  })
})

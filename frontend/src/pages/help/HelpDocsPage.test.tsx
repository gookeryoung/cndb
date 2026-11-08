/** 帮助文档页（ADR 0029 P0 / ADR 0036）—— 默认落点、深链选中、回落纠正、页内目录、移动端与引导重放。 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { renderProviders } from '@/test/render-providers'
import { useOnboardingStore } from '@/store/onboarding'
import type { ResponsiveState } from '@/hooks/useResponsive'
import HelpDocsPage from './HelpDocsPage'
import { HELP_SECTIONS } from './helpNav'

let responsiveState: ResponsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
}

vi.mock('@/hooks/useResponsive', async () => {
    const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
    return { ...actual, useResponsive: () => responsiveState }
})

function renderHelp(route: string) {
    return renderProviders(
        <Routes>
            <Route path="/help" element={<HelpDocsPage />} />
            <Route path="/help/:sectionKey/:topicKey" element={<HelpDocsPage />} />
        </Routes>,
        { route },
    )
}

beforeEach(() => {
    responsiveState = {
        deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
        width: 1280, height: 800,
    }
    useOnboardingStore.setState({ tourRequested: false })
})

describe('HelpDocsPage 桌面端', () => {
    it('/help 默认落到首个主题，并渲染两级导航', async () => {
        renderHelp('/help')

        expect(await screen.findByRole('heading', { name: '认识晶格协同' })).toBeVisible()
        const aside = screen.getByTestId('help-docs-aside')
        expect(aside).toBeVisible()
        for (const section of HELP_SECTIONS) {
            // 面包屑会重复一级标题，故限定在侧栏内断言
            expect(within(aside).getByText(section.label)).toBeInTheDocument()
        }
        // 二级主题也能展开看到；当前主题选中（有 L3 的当前主题是 SubMenu）
        const current = screen.getByRole('menuitem', { name: '认识晶格协同' })
        expect(current.closest('li')?.className).toContain('ant-menu-submenu-selected')
    })

    it('深链 /help/tutorials/roles 渲染对应主题并选中二级项', async () => {
        renderHelp('/help/tutorials/roles')

        expect(await screen.findByRole('heading', { name: '权限与角色' })).toBeVisible()
        expect(screen.getByRole('menuitem', { name: '权限与角色' }).closest('li')?.className)
            .toContain('ant-menu-submenu-selected')
        expect(within(screen.getByTestId('help-docs-aside')).getByText('教程&最佳实践')).toBeInTheDocument()
    })

    it('点击二级主题切换内容', async () => {
        renderHelp('/help')

        fireEvent.click(await screen.findByRole('menuitem', { name: '字段类型' }))
        await waitFor(() => {
            expect(screen.getByRole('heading', { name: '字段类型' })).toBeVisible()
        })
    })

    it('未知 section / topic 回落到首个主题', async () => {
        renderHelp('/help/nope/nope')

        expect(await screen.findByRole('heading', { name: '认识晶格协同' })).toBeVisible()
    })

    it('「重新播放新手引导」发出 requestTour 信号', async () => {
        renderHelp('/help')

        fireEvent.click(await screen.findByTestId('help-docs-replay-tour'))
        expect(useOnboardingStore.getState().tourRequested).toBe(true)
    })
})

describe('HelpDocsPage 页内目录（L3 / L4）', () => {
    it('正文按 L3 小节渲染二级标题，并出现在本页目录里', async () => {
        renderHelp('/help/tutorials/roles')

        // L3 小节渲染为 h2，与目录项一一对应
        const h2 = await screen.findByRole('heading', { name: '角色模型', level: 2 })
        expect(h2).toBeVisible()
        const toc = screen.getByTestId('help-docs-toc')
        expect(within(toc).getByTestId('help-toc-model')).toBeVisible()
        expect(within(toc).getByText('行级权限规则')).toBeVisible()
    })

    it('L4 条目渲染为三级标题，并随所属小节进入目录', async () => {
        renderHelp('/help/troubleshooting/guide')

        expect(await screen.findByRole('heading', { name: '提示登录已过期', level: 3 })).toBeVisible()
        const toc = screen.getByTestId('help-docs-toc')
        expect(within(toc).getByTestId('help-toc-login')).toBeVisible()
        expect(within(toc).getByText('提示登录已过期')).toBeVisible()
    })

    it('只有正文的小节不产生 L4 层级', async () => {
        renderHelp('/help/tutorials/roles')

        expect(await screen.findByRole('heading', { name: '视图可见性', level: 2 })).toBeVisible()
        expect(screen.queryByRole('heading', { name: '视图可见性', level: 3 })).toBeNull()
        expect(within(screen.getByTestId('help-docs-toc')).getAllByText('视图可见性')).toHaveLength(1)
    })

    it('点击目录项定位到对应小节并高亮', async () => {
        renderHelp('/help/tutorials/roles')

        fireEvent.click(await screen.findByTestId('help-toc-row-level'))
        await waitFor(() => {
            expect(screen.getByTestId('help-toc-row-level').className).toContain('is-active')
        })
        // 锚点目标真实存在（地址栏写入 hash 依赖浏览器路由，单测只校验可定位）
        expect(document.getElementById('help-row-level')).toBeTruthy()
    })

    it('带锚点的深链直接高亮对应小节', async () => {
        renderHelp('/help/tutorials/roles#help-row-level')

        await waitFor(() => {
            expect(screen.getByTestId('help-toc-row-level').className).toContain('is-active')
        })
        expect(document.getElementById('help-row-level')).toBeTruthy()
    })
})

describe('HelpDocsPage 侧栏就地 L3 目录（ADR 0105 §5.1）', () => {
    it('选中主题在侧栏就地展开 L3，未选中主题不展开', async () => {
        renderHelp('/help/tutorials/field-types')

        const aside = screen.getByTestId('help-docs-aside')
        // 当前主题的 L3 直接出现在侧栏（数据复用正文，不走额外请求）
        expect(await within(aside).findByRole('menuitem', { name: '分类总览' })).toBeVisible()
        expect(within(aside).getByRole('menuitem', { name: '高级类型' })).toBeVisible()
        // 其它主题保持单层：roles 的 L3 不会出现
        expect(within(aside).queryByRole('menuitem', { name: '角色模型' })).toBeNull()
    })

    it('点击侧栏 L3 定位到对应小节并高亮', async () => {
        renderHelp('/help/tutorials/roles')

        const aside = screen.getByTestId('help-docs-aside')
        fireEvent.click(await within(aside).findByRole('menuitem', { name: '行级权限规则' }))
        await waitFor(() => {
            expect(screen.getByTestId('help-toc-row-level').className).toContain('is-active')
        })
        expect(document.getElementById('help-row-level')).toBeTruthy()
    })

    it('页首导语回答「本页你能学到什么」与「适合谁」', async () => {
        renderHelp('/help/tutorials/roles')

        const intro = await screen.findByTestId('help-topic-intro')
        expect(intro).toHaveTextContent('本页你能学到什么')
        expect(intro).toHaveTextContent('适合谁')
    })
})

describe('HelpDocsPage 窄屏', () => {
    it('侧栏收进抽屉、页内目录不占用正文宽度，选中主题后抽屉自动关闭', async () => {
        responsiveState = {
            deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
            width: 375, height: 667,
        }
        renderHelp('/help')

        expect(screen.queryByTestId('help-docs-aside')).toBeNull()
        expect(screen.queryByTestId('help-docs-toc')).toBeNull()
        expect(await screen.findByRole('heading', { name: '认识晶格协同' })).toBeVisible()

        fireEvent.click(screen.getByTestId('help-docs-menu-btn'))
        expect(await screen.findByTestId('help-docs-nav-drawer')).toBeVisible()

        fireEvent.click(screen.getByRole('menuitem', { name: '常见问题' }))
        await waitFor(() => {
            expect(screen.getByRole('heading', { name: '常见问题' })).toBeVisible()
        })
        await waitFor(() => {
            expect(screen.getByTestId('help-docs-nav-drawer')).not.toBeVisible()
        })
    })
})

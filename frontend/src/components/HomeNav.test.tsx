/** 主页导航 rail 单测（需求 0160 C1 / C4 / C9，A′ 口径）.
 *
 * 覆盖：只承载独有信息（新建 / 最近访问 / 全部工作区）、不重复顶栏与右栏入口、
 * 最近访问单行 label（含 title 提示）与「仍可读」过滤、当前项选中态、移动端变体。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes, useLocation } from 'react-router-dom'

import HomeNav from './HomeNav'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { RECENT_WORKSPACES_KEY } from '@/utils/recentWorkspaces'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}{loc.search}</span>
}

function renderNav(props: { mobile?: boolean } = {}, route = '/w') {
  return renderProviders(
    <Routes>
      <Route
        path="*"
        element={(
          <>
            <HomeNav {...props} />
            <LocationProbe />
          </>
        )}
      />
    </Routes>,
    { route },
  )
}

/** 条目所在的可选中 Menu 行（antd Menu 选中态落在 li 上） */
function menuRow(testid: string): HTMLElement | null {
  return screen.getByTestId(testid).closest('.ant-menu-item') as HTMLElement | null
}

describe('HomeNav', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('只渲染新建 / 最近访问 / 全部工作区三段，不重复顶栏与右栏入口（A′）', async () => {
    server.use(http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json([{
      view_id: 7, name: '本周待办', view_type: 'grid', is_default: false, visibility: 'table',
      filter_count: 0, sort_count: 0, table_id: 100, table_name: '任务', workspace_id: 10,
      workspace_name: '测试工作区', updated_at: null,
    }])))
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() - 60_000 },
    ]))
    renderNav()

    const nav = await screen.findByTestId('sider-home')
    expect(nav).toHaveAttribute('aria-label', '主页导航')
    expect(within(nav).getByTestId('home-nav-create')).toBeVisible()
    expect(await within(nav).findByTestId('home-nav-recent-10')).toBeVisible()
    await waitFor(() =>
      expect(within(nav).getByTestId('home-nav-all')).toHaveTextContent('全部工作区1'))
    expect(within(nav).getByText('最近访问')).toBeVisible()
    expect(within(nav).getByText('工作区')).toBeVisible()

    // 重复入口一律不渲染：团队（顶栏切换器）/ 收藏视图（右栏）/ 帮助（顶栏）/ 管理团队（= 点团队）
    expect(within(nav).queryByTestId('home-nav-help')).toBeNull()
    expect(within(nav).queryByTestId('home-nav-manage-teams')).toBeNull()
    expect(within(nav).queryByTestId('home-nav-view-7')).toBeNull()
    expect(within(nav).queryByTestId('home-nav-team-500')).toBeNull()
    expect(within(nav).queryByText('收藏视图')).toBeNull()
    expect(within(nav).queryByText('团队')).toBeNull()
  })

  it('最近访问为单行 label：名称 + 相对时间，并有完整 title 提示', async () => {
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() - 60_000 },
    ]))
    renderNav()

    const item = await screen.findByTestId('home-nav-recent-10')
    // 单行结构：名称与相对时间同层（不再嵌套 block 双行，避免被 40px 行高裁掉）
    expect(item).toHaveClass('cn-home-nav-recent')
    expect(item.querySelector('.cn-home-nav-recent-name')).toHaveTextContent('测试工作区')
    expect(item.querySelector('.cn-home-nav-recent-time')).not.toBeEmptyDOMElement()
    expect(item).toHaveAttribute('title')
    expect(item.getAttribute('title')).toContain('测试工作区')
  })

  it('最近访问只展示仍可读的工作区（已移除的工作区自动隐去）', async () => {
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() - 60_000 },
      { wid: '404', path: '/w/404/tables', ts: Date.now() - 120_000 },
    ]))
    renderNav()

    expect(await screen.findByTestId('home-nav-recent-10')).toBeVisible()
    expect(screen.queryByTestId('home-nav-recent-404')).toBeNull()
  })

  it('没有最近访问时不渲染「最近访问」分组', async () => {
    renderNav()

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.queryByText('最近访问')).toBeNull()
  })

  it('当前项选中态：主页 /w 高亮全部工作区', async () => {
    renderNav({}, '/w')

    await waitFor(() => expect(menuRow('home-nav-all')).toHaveClass('ant-menu-item-selected'))
  })

  it('点击新建工作区跳到 /w?create=1（与页内按钮同一弹窗入口）', async () => {
    renderNav()
    await userEvent.click(await screen.findByTestId('home-nav-create'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w?create=1'))
  })

  it('点击最近访问跳到上次所在模块，点击全部工作区回到 /w', async () => {
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() - 60_000 },
    ]))
    renderNav({}, '/teams/500')

    await userEvent.click(await screen.findByTestId('home-nav-recent-10'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables'))

    await userEvent.click(screen.getByTestId('home-nav-all'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w'))
  })

  it('移动端变体：只加上抽屉内边距，内容与桌面一致', async () => {
    renderNav({ mobile: true })

    const nav = await screen.findByTestId('sider-home')
    expect(nav).toHaveClass('cn-home-nav-mobile')
    expect(screen.getByTestId('home-nav-all')).toBeVisible()
    expect(screen.queryByTestId('home-nav-team-500')).toBeNull()
  })
})

/** 主页导航 rail 单测（需求 0160 C1 / C4 / C6 / C9）.
 *
 * 覆盖：分区渲染与计数、当前项选中态、移动端抽屉变体（不重复团队分区）、
 * 折叠态只留图标入口、最近访问来自本地存储（不额外请求）。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes, useLocation } from 'react-router-dom'

import HomeNav from './HomeNav'
import { renderProviders } from '@/test/render-providers'
import { mockTeam, mockWorkspace, server } from '@/test/msw'
import { RECENT_WORKSPACES_KEY } from '@/utils/recentWorkspaces'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}{loc.search}</span>
}

function renderNav(props: { collapsed?: boolean; mobile?: boolean; showTeams?: boolean } = {}, route = '/w') {
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

const favoriteViews = [{
  view_id: 7, name: '本周待办', view_type: 'grid', is_default: false, visibility: 'table',
  filter_count: 1, sort_count: 0, table_id: 100, table_name: '任务', workspace_id: 10,
  workspace_name: '测试工作区', updated_at: null,
}]

/** 条目所在的可选中 Menu 行（antd Menu 选中态落在 li 上） */
function menuRow(testid: string): HTMLElement | null {
  return screen.getByTestId(testid).closest('.ant-menu-item') as HTMLElement | null
}

describe('HomeNav', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('渲染新建 / 全部工作区 / 团队 / 收藏视图分区与计数', async () => {
    server.use(
      http.get('/api/v1/workspaces', () => HttpResponse.json([mockWorkspace])),
      http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json(favoriteViews)),
    )
    renderNav()

    const nav = await screen.findByTestId('sider-home')
    expect(nav).toHaveAttribute('aria-label', '主页导航')
    expect(within(nav).getByTestId('home-nav-create')).toBeVisible()
    await waitFor(() =>
      expect(within(nav).getByTestId('home-nav-all')).toHaveTextContent('全部工作区1'))
    expect(await within(nav).findByTestId('home-nav-team-500')).toHaveTextContent('研发部')
    expect(await within(nav).findByTestId('home-nav-view-7')).toHaveTextContent('本周待办')
    // 分区标题（复用 antd Menu group title）
    expect(within(nav).getByText('工作区')).toBeVisible()
    expect(within(nav).getByText('团队')).toBeVisible()
    expect(within(nav).getByText('收藏视图')).toBeVisible()
  })

  it('当前项选中态：主页 /w 高亮全部工作区，团队页高亮对应团队', async () => {
    const home = renderNav({}, '/w')
    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(menuRow('home-nav-all')).toHaveClass('ant-menu-item-selected')
    home.unmount()

    renderNav({}, '/teams/500')
    await waitFor(() => expect(menuRow('home-nav-team-500')).toHaveClass('ant-menu-item-selected'))
    expect(menuRow('home-nav-all')).not.toHaveClass('ant-menu-item-selected')
  })

  it('最近访问来自本地记录，只展示仍可读的工作区（不发额外请求）', async () => {
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() - 60_000 },
      { wid: '404', path: '/w/404/tables', ts: Date.now() - 120_000 },
    ]))
    renderNav()

    expect(await screen.findByText('最近访问')).toBeVisible()
    expect(screen.getByTestId('home-nav-recent-10')).toHaveTextContent('测试工作区')
    // 已不可读（不在 workspaces 列表）的条目自动隐去
    expect(screen.queryByTestId('home-nav-recent-404')).toBeNull()
  })

  it('折叠态只保留图标入口：不渲染最近访问与收藏视图', async () => {
    server.use(
      http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json(favoriteViews)),
    )
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() },
    ]))
    renderNav({ collapsed: true })

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.getByTestId('home-nav-create')).toBeVisible()
    expect(await screen.findByTestId('home-nav-team-500')).toBeVisible()
    expect(screen.queryByText('最近访问')).toBeNull()
    expect(screen.queryByText('收藏视图')).toBeNull()
  })

  it('移动端变体：showTeams=false 时团队分区交给抽屉既有分组，不重复渲染', async () => {
    renderNav({ mobile: true, showTeams: false })

    expect(await screen.findByTestId('sider-home')).toHaveClass('cn-home-nav-mobile')
    expect(screen.queryByTestId('home-nav-team-500')).toBeNull()
    expect(screen.queryByText('团队')).toBeNull()
    expect(screen.getByTestId('home-nav-all')).toBeVisible()
  })

  it('点击新建工作区跳到 /w?create=1（与页内按钮同一弹窗入口）', async () => {
    renderNav()
    await userEvent.click(await screen.findByTestId('home-nav-create'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w?create=1'))
  })

  it('点击团队条目与「管理团队 / 帮助文档」跳到对应页面', async () => {
    renderNav()
    await userEvent.click(await screen.findByTestId('home-nav-team-500'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(`/teams/${mockTeam.id}`))

    await userEvent.click(screen.getByTestId('home-nav-manage-teams'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/teams'))

    await userEvent.click(screen.getByTestId('home-nav-help'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/help'))
  })
})

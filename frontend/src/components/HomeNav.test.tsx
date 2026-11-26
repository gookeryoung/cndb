/** 主页导航 rail 单测（需求 0160 C1 / C4 / C9，A′ 口径）.
 *
 * 覆盖：独有信息承载（新建 / 最近访问 / 我的团队 / 全部工作区）、不重复右栏与顶栏动作入口、
 * 最近访问单行 label（含 title 提示）与「仍可读」过滤、团队条目跳转与选中态、当前项选中态、移动端变体。
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
  return <span data-testid="location">{loc.pathname}{loc.search}{loc.hash}</span>
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

const zeroSummary = {
  workspace_count: 1,
  team_count: 0,
  pending: { change_requests: 0, issues: 0, link_requests: 0, total: 0 },
  partial: false,
}

describe('HomeNav', () => {
  beforeEach(() => {
    window.localStorage.clear()
    server.use(http.get('/api/v1/home/summary', () => HttpResponse.json(zeroSummary)))
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
    expect(await within(nav).findByTestId('home-nav-recent-10')).toBeVisible()
    await waitFor(() =>
      expect(within(nav).getByTestId('home-nav-all')).toHaveTextContent('全部工作区1'))
    expect(within(nav).getByText('最近访问')).toBeVisible()
    expect(within(nav).getByText('我的工作区')).toBeVisible()

    // 我的视图（2026-11-26 新增）：聚合入口 + 收藏计数；不重复右栏的逐视图行
    expect(within(nav).getByTestId('home-nav-views')).toHaveTextContent('我的视图')
    expect(within(nav).getByTestId('home-nav-views')).toHaveTextContent('1')
    expect(within(nav).queryByTestId('home-nav-view-7')).toBeNull()
    // 动作入口也不渲染：新建工作区由页内工具栏与顶栏切换器底部承担，rail 只做导航
    expect(within(nav).queryByTestId('home-nav-create')).toBeNull()
    expect(within(nav).queryByText('新建工作区')).toBeNull()
    expect(within(nav).queryByTestId('home-nav-help')).toBeNull()
    expect(within(nav).queryByTestId('home-nav-manage-teams')).toBeNull()
    // 我的团队（2026-11-26 新增）：默认一个团队「研发部」
    expect(within(nav).getByText('我的团队')).toBeVisible()
    expect(within(nav).getByTestId('home-nav-team-500')).toHaveTextContent('研发部')
  })

  it('「我的团队」分区排在已收藏下方、工作区上方，行内标注角色', async () => {
    renderNav()

    const nav = await screen.findByTestId('sider-home')
    // 等团队条目渲染完成再取分组标题，避免查询未返回时分组缺失
    await within(nav).findByTestId('home-nav-team-500')
    const order = Array.from(nav.querySelectorAll('.ant-menu-item-group-title')).map(el => el.textContent)
    expect(order).toEqual(['我的团队', '我的工作区'])

    const row = within(nav).getByTestId('home-nav-team-500')
    expect(row.querySelector('.cn-home-nav-row-hint')).toHaveTextContent('团队所有者')
    expect(row).toHaveAttribute('title', '研发部 · 团队所有者')
  })

  it('点击团队条目跳到 /teams/:tid', async () => {
    renderNav({}, '/w')

    await userEvent.click(await screen.findByTestId('home-nav-team-500'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/teams/500'))
  })

  it('团队页（/teams/:tid?section=…）选中对应团队条目', async () => {
    renderNav({}, '/teams/500?section=members')

    await waitFor(() => {
      expect(menuRow('home-nav-team-500')).toHaveClass('ant-menu-item-selected')
      expect(menuRow('home-nav-all')).not.toHaveClass('ant-menu-item-selected')
    })
  })

  it('团队接口失败时静默隐藏「我的团队」分组，其余导航可用', async () => {
    server.use(http.get('/api/v1/teams', () => new HttpResponse(null, { status: 500 })))
    renderNav()

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.queryByText('我的团队')).toBeNull()
    expect(screen.queryByTestId('home-nav-team-500')).toBeNull()
  })

  it('最近访问为单行 label：名称 + 相对时间，并有完整 title 提示', async () => {
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '10', path: '/w/10/tables', ts: Date.now() - 60_000 },
    ]))
    renderNav()

    const item = await screen.findByTestId('home-nav-recent-10')
    // 单行结构：名称与相对时间同层（不再嵌套 block 双行，避免被 40px 行高裁掉）
    expect(item).toHaveClass('cn-home-nav-row')
    expect(item.querySelector('.cn-home-nav-row-name')).toHaveTextContent('测试工作区')
    expect(item.querySelector('.cn-home-nav-row-hint')).not.toBeEmptyDOMElement()
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
    // 内容与桌面一致：我的团队同样渲染
    expect(await screen.findByTestId('home-nav-team-500')).toBeVisible()
  })
  it('「已收藏」分区排在最近访问下方，并标注所属团队（需求 0160 补充）', async () => {
    server.use(http.get('/api/v1/workspaces', () => HttpResponse.json([
      {
        id: 10, name: '研发工作区', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_at: '', updated_at: '',
        pinned: true, team_id: 500, team: { id: 500, name: '研发部', slug: 'rd' },
      },
      {
        id: 11, name: '个人收藏区', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_at: '', updated_at: '', pinned: true,
      },
      {
        id: 12, name: '未收藏区', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_at: '', updated_at: '', pinned: false,
      },
    ])))
    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify([
      { wid: '12', path: '/w/12/tables', ts: Date.now() - 60_000 },
    ]))
    renderNav()

    const pinned = await screen.findByTestId('home-nav-pinned-10')
    expect(pinned).toHaveTextContent('研发工作区')
    // 收藏行右侧标注团队；个人工作区显示「个人」
    expect(pinned.querySelector('.cn-home-nav-row-hint')).toHaveTextContent('研发部')
    expect(screen.getByTestId('home-nav-pinned-11').querySelector('.cn-home-nav-row-hint'))
      .toHaveTextContent('个人')
    // 未收藏的工作区不进「已收藏」分区
    expect(screen.queryByTestId('home-nav-pinned-12')).toBeNull()

    // 「我的工作区」分组平铺未收藏工作区（12），已收藏的（10/11）不重复出现
    const wsRow = screen.getByTestId('home-nav-ws-12')
    expect(wsRow).toHaveTextContent('未收藏区')
    expect(wsRow.querySelector('.cn-home-nav-row-hint')).toHaveTextContent('个人')
    expect(screen.queryByTestId('home-nav-ws-10')).toBeNull()
    expect(screen.queryByTestId('home-nav-ws-11')).toBeNull()

    // 收藏图标与列表星标同色（琥珀），且尺寸钉在 Menu 图标档
    const star = pinned.closest('.ant-menu-item')?.querySelector('.cn-home-nav-star')
    expect(star).not.toBeNull()
    expect(star).toHaveStyle({ color: '#f59e0b' })

    // 分区顺序：最近访问 → 已收藏 → 我的团队 → 我的工作区
    const nav = screen.getByTestId('sider-home')
    const order = Array.from(nav.querySelectorAll('.ant-menu-item-group-title')).map(el => el.textContent)
    expect(order).toEqual(['最近访问', '已收藏', '我的团队', '我的工作区'])
  })

  it('没有收藏工作区时不渲染「已收藏」分区', async () => {
    renderNav()

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.queryByText('已收藏')).toBeNull()
  })

  it('点击「我的工作区」分组内的工作区行直达落地页（2026-11-26 新增）', async () => {
    renderNav({}, '/teams/500')

    await userEvent.click(await screen.findByTestId('home-nav-ws-10'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables'))
  })

  it('有待办时在「全部工作区」右侧显示聚合徽标，并带分解提示（ADR 0160 P2）', async () => {
    server.use(http.get('/api/v1/home/summary', () => HttpResponse.json({
      workspace_count: 1,
      team_count: 0,
      pending: { change_requests: 2, issues: 3, link_requests: 1, total: 6 },
      partial: false,
    })))
    renderNav()

    const badge = await screen.findByTestId('home-nav-pending')
    expect(badge).toHaveTextContent('6')
    expect(badge).toHaveAttribute('title', '待我处理：修改申请 2 · 问题 3 · 待审链接 1')
  })

  it('没有待办时不渲染徽标（不占位、不显示 0）', async () => {
    renderNav()

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.queryByTestId('home-nav-pending')).toBeNull()
  })

  it('聚合接口失败时静默隐藏徽标，主页其余入口仍可用', async () => {
    server.use(http.get('/api/v1/home/summary', () => new HttpResponse(null, { status: 500 })))
    renderNav()

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent('/w')
    expect(screen.queryByTestId('home-nav-pending')).toBeNull()
  })

  it('点击「我的视图」深链到 /w#my-views（定位右栏面板，2026-11-26 新增）', async () => {
    server.use(http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json([{
      view_id: 7, name: '本周待办', view_type: 'grid', is_default: false, visibility: 'table',
      filter_count: 0, sort_count: 0, table_id: 100, table_name: '任务', workspace_id: 10,
      workspace_name: '测试工作区', updated_at: null,
    }])))
    renderNav({}, '/teams/500')

    await userEvent.click(await screen.findByTestId('home-nav-views'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w#my-views'))
  })

  it('没有收藏视图时不渲染「我的视图」分组', async () => {
    renderNav()

    expect(await screen.findByTestId('home-nav-all')).toBeVisible()
    expect(screen.queryByText('我的视图')).toBeNull()
    expect(screen.queryByTestId('home-nav-views')).toBeNull()
  })
})

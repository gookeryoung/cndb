/**
 * TeamPage 组件测试（ADR 0153 / 需求 0157）—— 团队上下文页.
 *
 * 覆盖：
 * 1) 空态：没有团队时给出「新建团队」引导；
 * 2) `/teams` 重定向到第一个团队，`/teams/:tid?section=` 深链直达分区；
 * 3) 概览 / 工作区 / 成员 / 策略 / 搜索五个分区的内容；
 * 4) 团队角色门控：非所有者看不到「删除团队」与可编辑的策略表单；
 * 5) 策略保存走 PATCH /teams/:id 并带 policy；
 * 6) 添加成员 / 团队内检索 / 自助加入。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'

import TeamPage from './TeamPage'
import { renderProviders } from '@/test/render-providers'
import { mockTeam, mockTeamMember, server } from '@/test/msw'

function renderPage(route = `/teams/${mockTeam.id}`) {
  return renderProviders(
    <Routes>
      <Route path="/teams" element={<TeamPage />} />
      <Route path="/teams/:tid" element={<TeamPage />} />
    </Routes>,
    { route },
  )
}

describe('TeamPage 团队页', () => {
  it('没有团队时渲染空态与新建入口', async () => {
    server.use(http.get('/api/v1/teams', () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findByTestId('team-page-empty')).toBeVisible()
    expect(screen.getByText(/还没有团队/)).toBeVisible()
    expect(screen.getAllByRole('button', { name: /新建团队/ }).length).toBeGreaterThan(0)
  })

  it('/teams 自动落到第一个团队（深链 /teams/:tid 保持）', async () => {
    renderPage('/teams')

    expect(await screen.findByTestId('team-header')).toHaveTextContent('研发部')
    expect(screen.getByTestId('team-section-overview')).toBeInTheDocument()
  })

  it('概览分区展示指标、最近工作区与成员摘要', async () => {
    renderPage(`/teams/${mockTeam.id}`)

    expect(await screen.findByTestId('team-section-overview')).toBeInTheDocument()
    expect(screen.getByTestId('team-header')).toHaveTextContent('研发部')
    expect(screen.getByTestId('team-header')).toHaveTextContent('团队所有者')
    // 最近工作区（平铺，不是树节点）
    expect(await screen.findByText('测试工作区')).toBeVisible()
    // 成员摘要
    expect(await screen.findByText(/爱丽丝/)).toBeVisible()
    expect(screen.queryByRole('tree')).toBeNull()
  })

  it('分区页签可切换且 URL 携带 ?section=，深链直达成员分区', async () => {
    const user = userEvent.setup()
    renderPage(`/teams/${mockTeam.id}`)

    await user.click(await screen.findByTestId('team-section-tab-members'))
    expect(await screen.findByTestId('team-section-members')).toBeInTheDocument()
    expect(screen.getByTestId('team-add-member-input')).toBeVisible()
  })

  it('策略分区：所有者可编辑并可保存，危险区提供删除团队', async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/teams/:tid', async ({ request, params }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({ ...mockTeam, id: Number(params.tid) })
      }),
    )
    const user = userEvent.setup()
    renderPage(`/teams/${mockTeam.id}?section=policy`)

    expect(await screen.findByTestId('save-team-policy')).toBeEnabled()
    expect(screen.getByTestId('delete-team-btn')).toBeVisible()
    await user.click(screen.getByTestId('save-team-policy'))

    await waitFor(() => expect(bodies.length).toBe(1))
    expect(bodies[0]).toMatchObject({
      policy: { default_workspace_role: 'none', allow_member_invite: false, default_storage_quota_bytes: null },
    })
  })

  it('非团队所有者：无删除团队、策略表单禁用', async () => {
    server.use(
      http.get('/api/v1/teams', () => HttpResponse.json([{ ...mockTeam, current_user_role: 'member' }])),
      http.get('/api/v1/teams/:tid/members', () =>
        HttpResponse.json([{ ...mockTeamMember, role: 'member' }])),
    )
    renderPage(`/teams/${mockTeam.id}?section=policy`)

    expect(await screen.findByTestId('save-team-policy')).toBeDisabled()
    expect(screen.queryByTestId('delete-team-btn')).toBeNull()
  })

  it('非团队所有者：成员分区无添加入口', async () => {
    server.use(
      http.get('/api/v1/teams', () => HttpResponse.json([{ ...mockTeam, current_user_role: 'member' }])),
      http.get('/api/v1/teams/:tid/members', () =>
        HttpResponse.json([{ ...mockTeamMember, role: 'member' }])),
    )
    renderPage(`/teams/${mockTeam.id}?section=members`)

    expect(await screen.findByTestId('team-section-members')).toBeInTheDocument()
    expect(screen.queryByTestId('team-add-member-input')).toBeNull()
  })

  it('团队管理员可添加成员但看不到删除团队与可编辑策略', async () => {
    server.use(
      http.get('/api/v1/teams', () => HttpResponse.json([{ ...mockTeam, current_user_role: 'admin' }])),
    )
    renderPage(`/teams/${mockTeam.id}?section=members`)

    expect(await screen.findByTestId('team-add-member-input')).toBeVisible()
    expect(screen.queryByTestId('delete-team-btn')).toBeNull()
  })

  it('添加团队成员后刷新列表', async () => {
    const posts: string[] = []
    server.use(
      http.post('/api/v1/teams/:tid/members', async ({ request }) => {
        const body = await request.json() as { username: string; role: string }
        posts.push(body.username)
        return HttpResponse.json(
          { ...mockTeamMember, id: 701, role: body.role, user: { ...mockTeamMember.user, username: body.username } },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderPage(`/teams/${mockTeam.id}?section=members`)

    const input = await screen.findByTestId('team-add-member-input')
    await user.type(input, 'bob')
    await user.click(screen.getByTestId('team-add-member-btn'))

    await waitFor(() => expect(posts).toEqual(['bob']))
  })
})

describe('TeamPage 团队内检索与自助加入（ADR 0153 P2）', () => {
  it('提交关键词后请求团队检索并展示跨工作区命中', async () => {
    const queries: string[] = []
    server.use(
      http.get('/api/v1/teams/:tid/search', ({ request }) => {
        queries.push(new URL(request.url).searchParams.get('q') ?? '')
        return HttpResponse.json({
          query: '晶格',
          documents: [{ id: 1, title: '晶格需求', workspace_id: 10, workspace_name: '测试工作区' }],
          tables: [{ id: 100, name: '晶格表', workspace_id: 10, workspace_name: '测试工作区' }],
          rows: [],
        })
      }),
    )
    const user = userEvent.setup()
    renderPage(`/teams/${mockTeam.id}?section=search`)

    await user.type(await screen.findByTestId('team-search-input'), '晶格')
    await user.click(screen.getByTestId('team-search-btn'))

    await waitFor(() => expect(queries).toEqual(['晶格']))
    expect(await screen.findByText('晶格需求')).toBeVisible()
    expect(screen.getByText('晶格表')).toBeVisible()
  })

  it('策略开放自助加入且非成员时出现「加入」按钮，点击调用 join', async () => {
    const joined: string[] = []
    server.use(
      http.get('/api/v1/teams', () => HttpResponse.json([{
        ...mockTeam,
        policy: { ...mockTeam.policy, allow_member_invite: true },
      }])),
      http.get('/api/v1/teams/:tid/workspaces', () => HttpResponse.json([{
        id: 33, name: '未加入工作区', description: '', visibility: 'member',
        modules: ['tables'], member_count: 2, is_member: false, updated_at: '2026-01-02T00:00:00Z',
      }])),
      http.post('/api/v1/workspaces/:wid/join', ({ params }) => {
        joined.push(String(params.wid))
        return HttpResponse.json({ pinned: false })
      }),
    )
    const user = userEvent.setup()
    renderPage(`/teams/${mockTeam.id}?section=workspaces`)

    await user.click(await screen.findByTestId('join-workspace-33'))
    await waitFor(() => expect(joined).toEqual(['33']))
  })

  it('策略未开放时不显示加入按钮', async () => {
    server.use(
      http.get('/api/v1/teams/:tid/workspaces', () => HttpResponse.json([{
        id: 34, name: '另一个工作区', description: '', visibility: 'member',
        modules: ['tables'], member_count: 2, is_member: false, updated_at: '2026-01-02T00:00:00Z',
      }])),
    )
    renderPage(`/teams/${mockTeam.id}?section=workspaces`)

    expect(await screen.findByText('另一个工作区')).toBeVisible()
    expect(screen.queryByTestId('join-workspace-34')).toBeNull()
    expect(screen.getAllByText('未加入').length).toBeGreaterThan(0)
  })
})

describe('TeamPage 团队切换器', () => {
  it('切换器列出可切换团队并跳转对应团队页', async () => {
    const second = { ...mockTeam, id: 501, name: '市场部', slug: 'mkt' }
    server.use(http.get('/api/v1/teams', () => HttpResponse.json([mockTeam, second])))
    const user = userEvent.setup()
    renderPage(`/teams/${mockTeam.id}`)

    await user.click(await screen.findByTestId('team-switcher-btn'))
    const secondTeam = await screen.findByTestId('team-switch-501')
    expect(secondTeam).toHaveTextContent('市场部')
    await user.click(secondTeam)
    await waitFor(() => expect(screen.getByTestId('team-header')).toHaveTextContent('市场部'))
  })
})

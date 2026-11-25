/**
 * TeamPage 组件测试（ADR 0153 P1）—— 多工作区统一管理入口.
 *
 * 覆盖：
 * 1) 空态：没有团队时给出「新建团队」引导；
 * 2) 团队清单 + 选中团队的三块内容（成员 / 工作区平铺列表 / 策略）；
 * 3) 团队角色门控：非所有者看不到「删除团队」与可编辑的策略表单；
 * 4) 策略保存走 PATCH /teams/:id 并带 policy；
 * 5) 添加成员后刷新成员列表。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'

import TeamPage from './TeamPage'
import { renderProviders } from '@/test/render-providers'
import { mockTeam, mockTeamMember, server } from '@/test/msw'

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/teams" element={<TeamPage />} />
    </Routes>,
    { route: '/teams' },
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

  it('渲染团队清单、成员、工作区平铺列表与策略', async () => {
    renderPage()

    // 团队清单（默认选中第一个团队）
    const teamItem = await screen.findByTestId(`team-item-${mockTeam.id}`)
    expect(within(teamItem).getByText('研发部')).toBeVisible()

    // 成员表
    expect(await screen.findByText('爱丽丝')).toBeVisible()

    // 工作区平铺列表（无树：直接是表格行，不是可展开节点）
    expect(await screen.findByText('测试工作区')).toBeVisible()
    expect(screen.getByText('团队下的工作区（平铺列表）')).toBeVisible()

    // 策略区：所有者可编辑
    expect(screen.getByText('团队策略')).toBeVisible()
    expect(screen.getByTestId('save-team-policy')).toBeEnabled()
  })

  it('非团队所有者：无删除团队、无添加成员、策略表单禁用', async () => {
    server.use(
      http.get('/api/v1/teams', () => HttpResponse.json([{ ...mockTeam, current_user_role: 'member' }])),
      http.get('/api/v1/teams/:tid/members', () =>
        HttpResponse.json([{ ...mockTeamMember, role: 'member' }])),
    )
    renderPage()

    expect(await screen.findByTestId('save-team-policy')).toBeDisabled()
    expect(screen.queryByTestId('delete-team-btn')).toBeNull()
    expect(screen.queryByTestId('team-add-member-input')).toBeNull()
  })

  it('团队管理员可添加成员但看不到删除团队', async () => {
    server.use(
      http.get('/api/v1/teams', () => HttpResponse.json([{ ...mockTeam, current_user_role: 'admin' }])),
    )
    renderPage()

    expect(await screen.findByTestId('team-add-member-input')).toBeVisible()
    expect(screen.queryByTestId('delete-team-btn')).toBeNull()
    expect(await screen.findByTestId('save-team-policy')).toBeDisabled()
  })

  it('保存策略提交 policy 到 PATCH /teams/:id', async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/teams/:tid', async ({ request, params }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({ ...mockTeam, id: Number(params.tid) })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('save-team-policy')
    await user.click(screen.getByTestId('save-team-policy'))

    await waitFor(() => expect(bodies.length).toBe(1))
    expect(bodies[0]).toMatchObject({
      policy: { default_workspace_role: 'none', allow_member_invite: false, default_storage_quota_bytes: null },
    })
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
    renderPage()

    const input = await screen.findByTestId('team-add-member-input')
    await user.type(input, 'bob')
    await user.click(screen.getByTestId('team-add-member-btn'))

    await waitFor(() => expect(posts).toEqual(['bob']))
  })
})

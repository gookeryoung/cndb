/**
 * TeamAccessCard 组件测试（ADR 0154 P3.1 / B′）—— 工作区设置「团队只读授权」.
 *
 * 覆盖：
 * 1) 非 `MANAGE_ACCESS`（如团队管理员 / 编辑者）整卡不渲染；
 * 2) 空态 + 「授予团队」入口；
 * 3) 列表：团队名 / 只读标签 / 到期 / 已失效标记；
 * 4) 授权提交载荷（team_id + ttl_days）与撤销 DELETE；
 * 5) 文案明确「只读、不含管理权、不会加入成员列表」。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import TeamAccessCard from './TeamAccessCard'
import { server } from '@/test/msw'
import { renderProviders } from '@/test/render-providers'

const MOCK_TEAM = { id: 500, name: '分析部', slug: 'rd', description: '', policy: {}, created_by_id: 1, created_at: '', updated_at: '', current_user_role: 'owner', workspace_count: 0, member_count: 1 }

const MOCK_GRANT = {
  id: 900,
  workspace_id: 10,
  team_id: 500,
  team_name: '分析部',
  role: 'viewer',
  expires_at: '2026-12-25T00:00:00Z',
  active: true,
  note: '季度汇总',
  granted_by_id: 1,
  created_at: '2026-11-25T00:00:00Z',
  updated_at: '2026-11-25T00:00:00Z',
}

function mockBase(grants: unknown[] = []) {
  server.use(
    http.get('/api/v1/workspaces/:wid/team-access', () => HttpResponse.json(grants)),
    http.get('/api/v1/teams', () => HttpResponse.json([MOCK_TEAM])),
  )
}

function renderCard(canManage = true) {
  return renderProviders(<TeamAccessCard wid="10" canManage={canManage} />, { route: '/w/10/settings' })
}

describe('TeamAccessCard 团队只读授权', () => {
  it('无 MANAGE_ACCESS 时整卡不渲染', () => {
    mockBase()
    renderCard(false)
    expect(screen.queryByTestId('team-access-card')).toBeNull()
  })

  it('空态展示说明与「授予团队」入口', async () => {
    mockBase()
    renderCard()

    expect(await screen.findByTestId('team-access-card')).toBeVisible()
    expect(await screen.findByText(/还没有团队授权/)).toBeVisible()
    expect(screen.getAllByText(/只读/).length).toBeGreaterThan(0)
    expect(screen.getByTestId('team-access-add-btn')).toBeVisible()
  })

  it('列表展示团队 / 只读 / 到期 / 已失效', async () => {
    mockBase([
      MOCK_GRANT,
      { ...MOCK_GRANT, id: 901, team_name: '过期部', active: false, expires_at: '2026-01-01T00:00:00Z' },
    ])
    renderCard()

    const table = await screen.findByTestId('team-access-table')
    expect(await screen.findByText('分析部')).toBeVisible()
    expect(screen.getByText('过期部')).toBeVisible()
    expect(screen.getAllByText('只读').length).toBeGreaterThan(0)
    expect(screen.getByText('已失效')).toBeVisible()
    expect(table).toBeVisible()
  })

  it('授权提交 team_id 与有效期', async () => {
    mockBase()
    const bodies: Array<Record<string, unknown>> = []
    server.use(
      http.post('/api/v1/workspaces/:wid/team-access', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(MOCK_GRANT, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderCard()

    await user.click(await screen.findByTestId('team-access-add-btn'))
    await user.click(await screen.findByTestId('team-access-team-select'))
    await user.click(await screen.findByText('分析部', { selector: '.ant-select-item-option-content' }))
    const confirm = await waitFor(() => {
      const btn = document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement | null
      if (!btn) throw new Error('授权弹窗未展开')
      return btn
    })
    await user.click(confirm)

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ team_id: 500, ttl_days: 30 })
  })

  it('撤销调用 DELETE', async () => {
    mockBase([MOCK_GRANT])
    const deleted: string[] = []
    server.use(
      http.delete('/api/v1/workspaces/:wid/team-access/:aid', ({ params }) => {
        deleted.push(String(params.aid))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderCard()

    await user.click(await screen.findByTestId('team-access-revoke-900'))
    const confirm = await waitFor(() => {
      const btn = document.querySelector('.ant-popconfirm .ant-btn-primary') as HTMLElement | null
      if (!btn) throw new Error('Popconfirm 未展开')
      return btn
    })
    await user.click(confirm)
    await waitFor(() => expect(deleted).toEqual(['900']))
  })
})

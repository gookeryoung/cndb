/**
 * WorkspaceLinksPanel 组件测试（ADR 0154 P2）—— 消费方链接列表 / 申请 / 源侧审批.
 *
 * 覆盖：
 * 1) 空态 + 「申请链接」入口（EDIT_SETTINGS 默认 owner）；
 * 2) 列表状态展示（生效中 / 待批准 / 已到期）与「打开」可用性；
 * 3) 申请流程：选源工作区 → 选表 → 提交（断言 POST 载荷）；
 * 4) 撤回：DELETE 调用；
 * 5) 源侧审批：inbox 出现时显示批准 / 拒绝，批准带有效期。
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import WorkspaceLinksPanel from './WorkspaceLinksPanel'
import { server } from '@/test/msw'
import { installLinkHandlers, mockWorkspaceLink } from '@/test/linkFixtures'
import { renderProviders } from '@/test/render-providers'

const OTHER_WS = { id: 11, name: '源工作区', description: '', visibility: 'member' as const }

beforeEach(() => installLinkHandlers(server))

function mockWorkspaces() {
  server.use(
    http.get('/api/v1/workspaces', () =>
      HttpResponse.json([{ id: 10, name: '当前工作区', visibility: 'member' }, OTHER_WS])),
    http.get('/api/v1/workspaces/:wid/tables', () =>
      HttpResponse.json([{ id: 100, name: '销售明细', record_count: 3, field_count: 2, view_count: 1 }])),
  )
}

function renderPanel() {
  return renderProviders(<WorkspaceLinksPanel wid="10" />, { route: '/w/10/tables' })
}

describe('WorkspaceLinksPanel 外部链接面板', () => {
  it('无链接时展示空态与「申请链接」入口', async () => {
    mockWorkspaces()
    renderPanel()

    expect(await screen.findByTestId('workspace-links-panel')).toBeVisible()
    expect(await screen.findByText(/暂无外部链接/)).toBeVisible()
    expect(await screen.findByTestId('link-apply-btn')).toBeVisible()
  })

  it('列出链接并按状态展示；待批准 / 不可读时「打开」禁用', async () => {
    mockWorkspaces()
    server.use(
      http.get('/api/v1/workspaces/:wid/links', () =>
        HttpResponse.json([
          { ...mockWorkspaceLink, id: 801, alias: '可读表', status: 'active', readable: true },
          { ...mockWorkspaceLink, id: 802, alias: '待批准表', status: 'pending', readable: false },
          { ...mockWorkspaceLink, id: 803, alias: '不可读表', status: 'active', readable: false },
          { ...mockWorkspaceLink, id: 804, alias: '过期表', status: 'expired', readable: false },
        ])),
    )
    renderPanel()

    const table = await screen.findByTestId('workspace-links-table')
    expect(within(table).getByText('可读表')).toBeVisible()
    expect(within(table).getAllByText('生效中').length).toBeGreaterThan(0)
    expect(within(table).getByText('待源工作区批准')).toBeVisible()
    expect(within(table).getByText('已到期')).toBeVisible()
    expect(within(table).getByText('不可读')).toBeVisible()

    expect(screen.getByTestId('link-open-801')).toBeEnabled()
    expect(screen.getByTestId('link-open-802')).toBeDisabled()
    expect(screen.getByTestId('link-open-803')).toBeDisabled()
  })

  it('申请链接：选源工作区与表后提交正确载荷', async () => {
    mockWorkspaces()
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/workspaces/:wid/links', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(mockWorkspaceLink, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByTestId('link-apply-btn'))
    await user.click(await screen.findByTestId('link-apply-source'))
    await user.click(await screen.findByText('源工作区', { selector: '.ant-select-item-option-content' }))

    await user.click(await screen.findByTestId('link-apply-table'))
    await user.click(await screen.findByText('销售明细', { selector: '.ant-select-item-option-content' }))

    await user.click(screen.getByRole('button', { name: /提交申请/ }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ source_workspace_id: '11', target_table_id: 100, ttl_days: 30 })
  })

  it('申请链接：选「团队只读授权」后提交 audience=team 与团队 id', async () => {
    mockWorkspaces()
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.get('/api/v1/teams', () =>
        HttpResponse.json([{ id: 500, name: '分析部', slug: 'rd', description: '', policy: {},
          created_by_id: 1, created_at: '', updated_at: '', current_user_role: 'owner',
          workspace_count: 0, member_count: 1 }])),
      http.post('/api/v1/workspaces/:wid/links', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({ ...mockWorkspaceLink, audience: 'team' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByTestId('link-apply-btn'))
    await user.click(await screen.findByTestId('link-apply-source'))
    await user.click(await screen.findByText('源工作区', { selector: '.ant-select-item-option-content' }))
    await user.click(await screen.findByTestId('link-apply-table'))
    await user.click(await screen.findByText('销售明细', { selector: '.ant-select-item-option-content' }))

    // 切到「团队只读授权」→ 出现团队下拉
    await user.click(screen.getByRole('radio', { name: /团队只读授权/ }))
    await user.click(await screen.findByTestId('link-apply-team'))
    await user.click(await screen.findByText('分析部', { selector: '.ant-select-item-option-content' }))

    await user.click(screen.getByRole('button', { name: /提交申请/ }))
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ audience: 'team', team_id: 500 })
  })

  it('撤回链接调用 DELETE', async () => {
    mockWorkspaces()
    const deleted: string[] = []
    server.use(
      http.get('/api/v1/workspaces/:wid/links', () => HttpResponse.json([mockWorkspaceLink])),
      http.delete('/api/v1/workspaces/:wid/links/:lid', ({ params }) => {
        deleted.push(String(params.lid))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByTestId(`link-revoke-${mockWorkspaceLink.id}`))
    // Popconfirm 的确认键（行内也有「撤回」按钮，不能按名称全局匹配）
    const confirm = await waitFor(() => {
      const btn = document.querySelector('.ant-popconfirm .ant-btn-primary') as HTMLElement | null
      if (!btn) throw new Error('Popconfirm 未展开')
      return btn
    })
    await user.click(confirm)
    await waitFor(() => expect(deleted).toEqual([String(mockWorkspaceLink.id)]))
  })

  it('源工作区所有者看到待批准列表，批准时带上有效期', async () => {
    mockWorkspaces()
    const approved: Array<Record<string, unknown>> = []
    server.use(
      http.get('/api/v1/workspaces/:wid/links/inbox', () =>
        HttpResponse.json([{ ...mockWorkspaceLink, id: 900, alias: '待批链接', status: 'pending', readable: false }])),
      http.post('/api/v1/workspaces/:wid/links/:lid/approve', async ({ request, params }) => {
        approved.push({ id: params.lid, ...((await request.json()) as Record<string, unknown>) })
        return HttpResponse.json({ ...mockWorkspaceLink, id: Number(params.lid), status: 'active' })
      }),
    )
    const user = userEvent.setup()
    renderPanel()

    const inbox = await screen.findByTestId('workspace-links-inbox')
    expect(within(inbox).getByText('待批链接')).toBeVisible()

    await user.click(await screen.findByTestId('link-approve-900'))
    // 批准弹窗的确认键（行内也有「批准」链接）
    const confirm = await waitFor(() => {
      const btn = document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement | null
      if (!btn) throw new Error('批准弹窗未展开')
      return btn
    })
    await user.click(confirm)

    await waitFor(() => expect(approved).toHaveLength(1))
    expect(approved[0]).toMatchObject({ id: '900', ttl_days: 30 })
  })
})

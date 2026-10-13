/**
 * ChangeRequestDetailPage 修改申请详情测试 —— diff 渲染/冲突高亮/逐项 merge/门控/评论。
 *
 * 注：AntD portal 类 UI（message）断言用 await findBy*。
 */

import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import ChangeRequestDetailPage from './ChangeRequestDetailPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import { changeRequestsApi } from '@/api'
import type { ChangeRequestDetail } from '@/api'

const DETAIL: ChangeRequestDetail = {
  id: 51, workspace_id: 10, table_id: 20, title: '调整客户分级',
  description: '分级字段批量调整', status: 'open', stale: false, submitted_by_id: 2,
  reviewed_by_id: null, reviewed_at: null, review_comment: null,
  created_at: '2026-10-02T10:00:00', updated_at: '2026-10-02T10:00:00',
  items: [
    {
      id: 601, op: 'update', row_id: 9,
      base_values: { 分级: 'A', 备注: '老客户' },
      values: { 分级: 'B' },
      current_values: { 分级: 'A', 备注: '老客户' },
      field_conflicts: [],
    },
    {
      id: 602, op: 'delete', row_id: 12,
      base_values: { 姓名: '王五', 分级: 'C' },
      values: {},
      current_values: { 姓名: '王五', 分级: 'C' },
      field_conflicts: [],
    },
  ],
  actions: [
    { id: 1, action: 'comment', comment: '请尽快处理', acted_by_id: 2, created_at: '2026-10-02T10:05:00' },
  ],
}

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

function setupDetailHandlers(overrides: Partial<ChangeRequestDetail> = {}) {
  server.use(
    http.get('/api/v1/workspaces/10/tables/20/change-requests/51', () =>
      HttpResponse.json({ ...DETAIL, ...overrides })),
    http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({
        id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
        current_user_role: 'owner',
      })),
    http.get('/api/v1/workspaces/10/members', () =>
      HttpResponse.json([
        { id: 1, workspace_id: 10, user_id: 1, role: 'owner', pinned: false, user: { id: 1, username: 'alice', nickname: '爱丽丝', email: null } },
        { id: 2, workspace_id: 10, user_id: 2, role: 'editor', pinned: false, user: { id: 2, username: 'bob', nickname: null, email: null } },
      ])),
  )
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/change-requests/:requestId" element={<ChangeRequestDetailPage />} />
    </Routes>,
    { route: '/w/10/tables/20/change-requests/51', ...AUTH },
  )
}

describe('ChangeRequestDetailPage 修改申请详情', () => {
  it('渲染标题/状态/提交人/items diff 与动作流水', async () => {
    setupDetailHandlers()
    renderPage()

    expect(await screen.findByText(/调整客户分级/)).toBeInTheDocument()
    expect(screen.getByText('待审核')).toBeInTheDocument()
    expect(screen.getByText(/bob\s*提交于|提交于/)).toBeInTheDocument()
    // update 项 diff：基准值 → 申请值
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    // delete 项显示整行快照与「整行删除」（每个字段行各带一个标记）
    expect(screen.getByText('王五')).toBeInTheDocument()
    expect(screen.getAllByText(/整行删除/).length).toBeGreaterThanOrEqual(1)
    // 动作流水
    expect(screen.getByText('请尽快处理')).toBeInTheDocument()
    expect(screen.getByText(/评论：/)).toBeInTheDocument()
  })

  it('冲突字段高亮并提示当前值', async () => {
    // 字段级冲突 Tag 仅在 update 项 diff 行渲染，故冲突数据放在 update 项上
    setupDetailHandlers({
      items: [{ ...DETAIL.items[0]!, field_conflicts: ['分级'] }, DETAIL.items[1]!],
    })
    renderPage()

    // update 项头部统计 + 字段级红色 Tag
    expect(await screen.findByText('1 个字段基准已漂移')).toBeInTheDocument()
    const tags = await screen.findAllByText('基准已漂移')
    expect(tags.length).toBeGreaterThanOrEqual(1)
  })

  it('owner 可逐项决策合并：默认全部应用，合并后提示应用/跳过计数', async () => {
    // GET 用可变变量响应：merge 成功后 invalidate 回拉会覆盖 setQueryData，
    // handler 必须同步翻转状态，否则页面回退到 open
    let current = DETAIL
    setupDetailHandlers()
    server.use(
      http.get('/api/v1/workspaces/10/tables/20/change-requests/51', () =>
        HttpResponse.json(current)),
    )
    const mergeSpy = vi.spyOn(changeRequestsApi, 'merge').mockImplementation(async () => {
      current = { ...DETAIL, status: 'merged' }
      return { applied: 2, skipped: 0, request: current }
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /执\s*行\s*合\s*并/ }))

    await waitFor(() => expect(mergeSpy).toHaveBeenCalledTimes(1))
    // 默认两项均 apply
    expect(mergeSpy.mock.calls[0]![3]!.items).toEqual([
      { item_id: 601, action: 'apply' },
      { item_id: 602, action: 'apply' },
    ])
    expect(await screen.findByText('合并完成：应用 2 项，跳过 0 项')).toBeInTheDocument()
    // 合并后状态变为已合并
    expect(await screen.findByText('已合并')).toBeInTheDocument()
  })

  it('将 update 项切为「跳过」后决策同步到 merge 载荷', async () => {
    setupDetailHandlers()
    const mergeSpy = vi.spyOn(changeRequestsApi, 'merge').mockResolvedValue({
      applied: 1, skipped: 1, request: { ...DETAIL, status: 'merged' },
    })
    renderPage()

    // 第一个 item 的 Segmented 切到「跳过」（共两组，取第一个）
    const skipOptions = await screen.findAllByText('跳过')
    fireEvent.click(skipOptions[0]!)
    fireEvent.click(await screen.findByRole('button', { name: /执\s*行\s*合\s*并/ }))

    await waitFor(() => expect(mergeSpy).toHaveBeenCalledTimes(1))
    expect(mergeSpy.mock.calls[0]![3]!.items[0]).toEqual({ item_id: 601, action: 'skip' })
  })

  it('查看者无合并/关闭入口（后端 403 兜底）', async () => {
    setupDetailHandlers()
    server.use(
      http.get('/api/v1/workspaces/10', () =>
        HttpResponse.json({
          id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
          current_user_role: 'viewer',
        })),
    )
    renderPage()

    await screen.findByText(/调整客户分级/)
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /执\s*行\s*合\s*并/ })).toBeNull()
      expect(screen.queryByRole('button', { name: /关\s*闭\s*申\s*请/ })).toBeNull()
    })
  })

  it('stale 且为提交人时显示「刷新基准快照」入口并调用 update-base', async () => {
    setupDetailHandlers({ stale: true, submitted_by_id: 1 })
    const baseSpy = vi.spyOn(changeRequestsApi, 'updateBase').mockResolvedValue({ ...DETAIL, stale: false })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /刷\s*新\s*基\s*准\s*快\s*照/ }))
    await waitFor(() => expect(baseSpy).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('基准快照已刷新')).toBeInTheDocument()
  })

  it('发表评论后清空输入框', async () => {
    setupDetailHandlers()
    const addSpy = vi.spyOn(changeRequestsApi, 'addComment').mockResolvedValue({
      id: 2, action: 'comment', comment: '收到', acted_by_id: 1, created_at: '2026-10-03T09:00:00',
    })
    renderPage()

    fireEvent.change(await screen.findByPlaceholderText('写下评论…'), { target: { value: '收到' } })
    fireEvent.click(screen.getByRole('button', { name: /发\s*表\s*评\s*论/ }))

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith('10', '20', '51', '收到'))
    await waitFor(() => expect(screen.getByPlaceholderText('写下评论…')).toHaveValue(''))
  })
})

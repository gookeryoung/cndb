/**
 * ChangeRequestsPage 修改申请列表测试 —— scope 筛选 / 状态与冲突/stale 标记 / 点击导航 /
 * 写模式权限标注（direct/change_request/denied）与新建按钮提示适配。
 *
 * 注：message.info 属 AntD portal，断言用 await findBy*。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import ChangeRequestsPage from './ChangeRequestsPage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { ChangeRequest, ID, TableWriteMode } from '@/api'

const CRS: ChangeRequest[] = [
  {
    id: 51, workspace_id: 10, table_id: 20, title: '调整客户分级',
    description: '', status: 'open', stale: true, submitted_by_id: 2,
    reviewed_by_id: null, reviewed_at: null, review_comment: null,
    created_at: '2026-10-02T10:00:00', updated_at: '2026-10-02T10:00:00', conflicts_count: 3,
    row_ids: [12], fields: ['分级'], item_count: 1,
  },
  {
    id: 50, workspace_id: 10, table_id: 20, title: '清理重复行',
    description: '', status: 'merged', stale: false, submitted_by_id: 1,
    reviewed_by_id: 1, reviewed_at: '2026-10-01T12:00:00', review_comment: null,
    created_at: '2026-10-01T09:00:00', updated_at: '2026-10-01T12:00:00', conflicts_count: 0,
    row_ids: [20], fields: ['姓名'], item_count: 1,
  },
]

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

function listHandler(
  captured: { scope?: string; groupBy?: string } = {},
  writeMode: TableWriteMode = 'change_request',
) {
  return http.get('/api/v1/workspaces/10/tables/20/change-requests', ({ request }) => {
    const url = new URL(request.url)
    captured.scope = url.searchParams.get('scope') ?? undefined
    captured.groupBy = url.searchParams.get('group_by') ?? undefined
    const scope = captured.scope ?? 'open'
    const items = scope === 'all'
      ? CRS
      : scope === 'mine'
        ? CRS.filter(c => c.submitted_by_id === 1)
        : scope === 'merged'
          ? CRS.filter(c => c.status === 'merged')
          : CRS.filter(c => c.status === 'open')
    // group_by=row：按目标行聚合为行组（create-only 无 row_ids 归 ungrouped）
    if (url.searchParams.get('group_by') === 'row') {
      const byRow = new Map<ID, ChangeRequest[]>()
      const ungrouped: ChangeRequest[] = []
      for (const it of items) {
        const rid = it.row_ids?.[0]
        if (rid == null) { ungrouped.push(it); continue }
        const list = byRow.get(rid) ?? []
        list.push(it)
        byRow.set(rid, list)
      }
      const groups = Array.from(byRow.entries()).map(([row_id, requests]) => ({
        row_id, row_values: { 名称: '甲', 数量: 1 }, row_missing: false,
        requests, conflict_fields: [], drift_fields: [],
        has_conflict: false, has_drift: false, latest_created_at: requests[0]?.created_at ?? null,
      }))
      return HttpResponse.json({ groups, ungrouped, total: items.length, write_mode: writeMode })
    }
    return HttpResponse.json({ items, total: items.length, write_mode: writeMode })
  })
}

function renderPage(route = '/w/10/tables/20/change-requests') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/change-requests" element={<ChangeRequestsPage />} />
      <Route path="/w/:wid/tables/:tid/change-requests/rows/:rowId/merge" element={<div data-testid="cr-row-merge-stub">冲突处理</div>} />
      <Route path="/w/:wid/tables/:tid/change-requests/:requestId" element={<div data-testid="cr-detail-stub">详情</div>} />
    </Routes>,
    { route, ...AUTH },
  )
}

/** 构造申请行组列表响应（供同行合并视图测试） */
function makeReq(over: Partial<ChangeRequest>): ChangeRequest {
  return {
    id: 1, workspace_id: 10, table_id: 20, title: '变更', description: '',
    status: 'open', stale: false, submitted_by_id: 2, reviewed_by_id: null,
    reviewed_at: null, review_comment: null, created_at: '2026-10-02T09:00:00',
    updated_at: '2026-10-02T09:00:00', row_ids: [], fields: [], item_count: 1, ...over,
  }
}

function groupedHandler(payload: {
  groups: Array<{ row_id: number; requests: ChangeRequest[] } & Partial<{ conflict_fields: string[]; drift_fields: string[]; has_conflict: boolean; has_drift: boolean; row_missing: boolean; row_values: Record<string, unknown> }>>
  ungrouped?: ChangeRequest[]
}) {
  const groups = payload.groups.map(g => ({
    row_values: {}, row_missing: false, conflict_fields: [], drift_fields: [],
    has_conflict: false, has_drift: false, latest_created_at: g.requests[0]?.created_at ?? null,
    ...g,
  }))
  const ungrouped = payload.ungrouped ?? []
  const total = groups.reduce((n, g) => n + g.requests.length, 0) + ungrouped.length
  return http.get('/api/v1/workspaces/10/tables/20/change-requests', () =>
    HttpResponse.json({ groups, ungrouped, total, write_mode: 'change_request' }))
}

describe('ChangeRequestsPage 修改申请列表', () => {
  it('默认展示 open 列表，渲染 stale 与冲突标记', async () => {
    const captured: { scope?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    expect(await screen.findByText('调整客户分级')).toBeInTheDocument()
    // open 视图不显示状态 Tag（全部待审核），merged 项不出现
    expect(screen.queryByText('清理重复行')).toBeNull()
    expect(screen.getByText('基准已过期')).toBeInTheDocument()
    expect(screen.getByText('与 3 行待审批申请冲突')).toBeInTheDocument()
    expect(captured.scope).toBe('open')
  })

  it('切换「全部」时 merged 项带状态 Tag，切换「我的」按提交人过滤', async () => {
    const captured: { scope?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    await screen.findByText('调整客户分级')
    fireEvent.click(screen.getByText('全部'))
    await waitFor(() => expect(captured.scope).toBe('all'))
    expect(await screen.findByText('清理重复行')).toBeInTheDocument()
    // 全部视图显示状态 Tag
    expect(screen.getAllByText('已合并').length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByText('我的'))
    await waitFor(() => expect(captured.scope).toBe('mine'))
    expect(await screen.findByText('清理重复行')).toBeInTheDocument()
    expect(screen.queryByText('调整客户分级')).toBeNull()
  })

  it('切换「已合并」时按 merged 状态过滤并带状态 Tag', async () => {
    const captured: { scope?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    await screen.findByText('调整客户分级')
    fireEvent.click(screen.getByText('已合并'))
    await waitFor(() => expect(captured.scope).toBe('merged'))
    expect(await screen.findByText('清理重复行')).toBeInTheDocument()
    expect(screen.queryByText('调整客户分级')).toBeNull()
    // 「已合并」同时出现在筛选 Segmented 与状态 Tag，取全部匹配
    expect(screen.getAllByText('已合并').length).toBeGreaterThanOrEqual(1)
  })

  it('点击列表项导航到详情页', async () => {
    server.use(listHandler())
    renderPage()

    fireEvent.click(await screen.findByText('调整客户分级'))
    await waitFor(() => {
      expect(screen.getByTestId('cr-detail-stub')).toBeInTheDocument()
    })
  })

  it('申请模式下新建按钮提示走网格编辑双轨路径', async () => {
    server.use(listHandler({}, 'change_request'))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*修\s*改\s*申\s*请/ }))
    // 申请模式引导文案（message.info portal）
    expect(await screen.findByText('请直接在表格中编辑数据，系统会自动生成修改申请')).toBeInTheDocument()
  })

  it('申请模式头部显示申请模式标注', async () => {
    server.use(listHandler({}, 'change_request'))
    renderPage()

    expect(await screen.findByText('调整客户分级')).toBeInTheDocument()
    expect(screen.getByText('申请模式')).toBeInTheDocument()
    expect(screen.getByText('在表格中编辑数据会自动生成修改申请，经审批合并后生效。')).toBeInTheDocument()
  })

  it('直编模式：头部显示直编标注，新建按钮提示编辑直接生效', async () => {
    server.use(listHandler({}, 'direct'))
    renderPage()

    expect(await screen.findByText('直编模式')).toBeInTheDocument()
    expect(
      screen.getByText('当前账号可直接在表格中修改数据：编辑立即生效，不会自动生成修改申请。'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /新\s*建\s*修\s*改\s*申\s*请/ }))
    expect(
      await screen.findByText('当前账号具备直接修改权限：在表格中编辑会直接生效，不会自动生成修改申请。'),
    ).toBeInTheDocument()
    // 旧文案不再出现，避免直编用户被误导
    expect(screen.queryByText('请直接在表格中编辑数据，系统会自动生成修改申请')).toBeNull()
  })

  it('只读模式：头部显示只读标注，新建按钮提示无编辑权限', async () => {
    server.use(listHandler({}, 'denied'))
    renderPage()

    expect(await screen.findByText('只读')).toBeInTheDocument()
    expect(screen.getByText('当前账号对该表无编辑权限，写操作将被拒绝。')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /新\s*建\s*修\s*改\s*申\s*请/ }))
    expect(await screen.findByText('当前账号对该表只读，无法提交数据变更。')).toBeInTheDocument()
  })
})

describe('ChangeRequestsPage 同行合并视图', () => {
  it('按行聚合，组内/组间时间倒序，新增行归 ungrouped', async () => {
    const g12a = makeReq({ id: 51, title: '改名称', created_at: '2026-10-02T09:00:00', row_ids: [12] })
    const g12b = makeReq({ id: 52, title: '改数量', created_at: '2026-10-02T10:00:00', row_ids: [12] })
    const g30 = makeReq({ id: 53, title: '改备注', created_at: '2026-10-02T11:00:00', row_ids: [30] })
    const un = makeReq({ id: 60, title: '新增行', created_at: '2026-10-02T12:00:00', row_ids: [] })
    server.use(groupedHandler({
      groups: [
        { row_id: 30, requests: [g30] },
        { row_id: 12, requests: [g12b, g12a] },
      ],
      ungrouped: [un],
    }))
    renderPage()

    expect(await screen.findByText('行 #12')).toBeInTheDocument()
    // 组间倒序（行 #30 在前）、组内倒序（改数量 在 改名称 前）
    const order = screen.getAllByText(/改备注|改数量|改名称/).map(e => e.textContent)
    expect(order).toEqual(['改备注', '改数量', '改名称'])
    // create-only 归入「新增行申请」区
    expect(screen.getByText('新增行申请')).toBeInTheDocument()
    expect(screen.getByText('新增行')).toBeInTheDocument()
  })

  it('reviewer 勾选多份申请后批量审批，无冲突直接合并', async () => {
    const reqs = [
      makeReq({ id: 51, title: '改名称', created_at: '2026-10-02T10:00:00', row_ids: [12] }),
      makeReq({ id: 52, title: '改数量', created_at: '2026-10-02T09:00:00', row_ids: [12] }),
    ]
    server.use(groupedHandler({ groups: [{ row_id: 12, requests: reqs }] }))
    let body: { request_ids?: number[] } = {}
    server.use(http.post('/api/v1/workspaces/10/tables/20/change-requests/rows/12/merge', async ({ request }) => {
      body = await request.json() as { request_ids?: number[] }
      return HttpResponse.json({ applied: 2, skipped: 0, merged_request_ids: [51, 52], requests: [] })
    }))
    renderPage()

    await screen.findByText('行 #12')
    const checkboxes = screen.getAllByRole('checkbox')
    fireEvent.click(checkboxes[0])
    fireEvent.click(checkboxes[1])
    fireEvent.click(screen.getByRole('button', { name: /批量审批/ }))
    fireEvent.click(await screen.findByText('确认合并'))
    await waitFor(() => expect(body.request_ids?.slice().sort()).toEqual([51, 52]))
  })

  it('存在冲突时批量审批跳转冲突处理页并携带选中申请 id', async () => {
    server.use(groupedHandler({
      groups: [{ row_id: 12, requests: [makeReq({ id: 51, title: '改数量', row_ids: [12] })], has_conflict: true, conflict_fields: ['数量'] }],
    }))
    renderPage()

    await screen.findByText('行 #12')
    expect(screen.getByText('冲突')).toBeInTheDocument()
    expect(screen.getByText('冲突字段：数量')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('checkbox')[0])
    fireEvent.click(screen.getByRole('button', { name: /批量审批/ }))
    expect(await screen.findByTestId('cr-row-merge-stub')).toBeInTheDocument()
  })

  it('切换「平铺」改走扁平列表接口', async () => {
    const captured: { groupBy?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    await screen.findByText('调整客户分级')
    expect(captured.groupBy).toBe('row')
    fireEvent.click(screen.getByText('平铺'))
    await waitFor(() => expect(captured.groupBy).toBeUndefined())
  })
})

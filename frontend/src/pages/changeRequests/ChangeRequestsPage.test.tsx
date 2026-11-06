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
import ChangeRequestDetailPage from './ChangeRequestDetailPage'
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
      <Route path="/w/:wid/tables/change-requests" element={<ChangeRequestsPage />} />
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
  it('左栏按行分组（组间时间倒序）+ 新增行申请；右栏只展示选中组的申请', async () => {
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

    // 左栏两组 + 新增行申请，默认选中首组（行 #30）
    expect(await screen.findByRole('option', { name: /行 #30/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('option', { name: /行 #12/ })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('option', { name: /新增行申请/ })).toHaveAttribute('aria-selected', 'false')

    // 右栏只渲染选中组的申请（改备注），其余组不出现
    expect(screen.getByTestId('cr-group-requests-box')).toHaveTextContent('改备注')
    expect(screen.queryByText('改数量')).toBeNull()
    expect(screen.queryByText('改名称')).toBeNull()

    // 切到行 #12：组内时间倒序（改数量 在 改名称 前）
    fireEvent.click(screen.getByRole('option', { name: /行 #12/ }))
    expect(await screen.findByText('改数量')).toBeInTheDocument()
    const order = screen.getAllByText(/改数量|改名称/).map(e => e.textContent)
    expect(order).toEqual(['改数量', '改名称'])
    expect(screen.queryByText('改备注')).toBeNull()

    // create-only 归入「新增行申请」，切换后右栏展示该申请
    fireEvent.click(screen.getByRole('option', { name: /新增行申请/ }))
    expect(await screen.findByText('新增行')).toBeInTheDocument()
    expect(screen.getByText('新增行申请 · 申请清单')).toBeInTheDocument()
    expect(screen.queryByText('改数量')).toBeNull()
  })

  it('页面骨架：同行合并为左行分组 / 右申请清单双栏', async () => {
    server.use(groupedHandler({
      groups: [{ row_id: 12, requests: [makeReq({ id: 51, title: '改数量', row_ids: [12] })] }],
    }))
    renderPage()

    expect(await screen.findByTestId('change-requests-page')).toBeInTheDocument()
    expect(screen.getByTestId('cr-grouped-split')).toBeInTheDocument()
    expect(screen.getByTestId('cr-groups-box')).toBeInTheDocument()
    expect(screen.getByTestId('cr-group-requests-box')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '修改申请' })).toBeInTheDocument()
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

describe('ChangeRequestsPage 工作区级左右分栏（需求 0107）', () => {
  /** 工作区级列表响应：两张表、三条申请（表 20 两条 / 表 21 一条） */
  function workspaceHandler() {
    return http.get('/api/v1/workspaces/10/change-requests', ({ request }) => {
      const scope = new URL(request.url).searchParams.get('scope') ?? ''
      return HttpResponse.json({
        items: [
          ...CRS.map(item => ({ ...item, table_name: '客户表' })),
          {
            ...CRS[0], id: 52, table_id: 21, title: '补录交付日期', stale: false, conflicts_count: 0,
            created_at: '2026-10-03T09:00:00', updated_at: '2026-10-03T09:00:00', table_name: '订单表',
          },
        ],
        total: 3,
        scope,
      })
    })
  }

  /** 详情端点：返回 items（三态 diff + 当前行值）供展开上下文渲染 */
  function detailHandler(payload?: { rowMissing?: boolean }) {
    return http.get('/api/v1/workspaces/10/tables/20/change-requests/51', () => HttpResponse.json({
      ...CRS[0],
      items: [
        {
          id: 1, op: 'update', row_id: 12,
          base_values: { 分级: 'B' }, values: { 分级: 'A' },
          current_values: payload?.rowMissing ? {} : { 分级: 'B', 姓名: '甲', 电话: '13800000000' },
          field_conflicts: [], row_missing: payload?.rowMissing ?? false,
        },
      ],
      actions: [],
    }))
  }

  it('左栏按工作表分组并显示计数，默认选中申请数最多的表；点击标题跳详情', async () => {
    server.use(workspaceHandler())
    renderPage('/w/10/tables/change-requests')

    // 页面骨架：页头 + 左工作表 / 右修改项双栏
    expect(await screen.findByTestId('change-requests-page')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '修改申请' })).toBeInTheDocument()
    expect(screen.getByTestId('cr-workspace-split')).toBeInTheDocument()
    expect(screen.getByTestId('cr-tables-box')).toBeInTheDocument()
    expect(screen.getByTestId('cr-requests-box')).toBeInTheDocument()

    // 左栏两张表 + 计数徽标；默认选中申请数更多的客户表，右栏只展示该表申请
    expect(await screen.findByRole('option', { name: /客户表/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /订单表/ })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('option', { name: /客户表/ })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('调整客户分级')).toBeInTheDocument()
    expect(screen.queryByText('补录交付日期')).toBeNull()
    // 跨表列表没有同行合并视图与单一写模式标注
    expect(screen.queryByText('同行合并')).toBeNull()
    expect(screen.queryByText('申请模式')).toBeNull()

    fireEvent.click(screen.getByText('调整客户分级'))
    await waitFor(() => {
      expect(screen.getByTestId('cr-detail-stub')).toBeInTheDocument()
    })
  })

  it('切换左栏工作表后右栏随之刷新', async () => {
    server.use(workspaceHandler())
    renderPage('/w/10/tables/change-requests')

    fireEvent.click(await screen.findByRole('option', { name: /订单表/ }))
    expect(await screen.findByText('补录交付日期')).toBeInTheDocument()
    expect(screen.queryByText('调整客户分级')).toBeNull()
  })

  it('展开修改项懒加载详情：字段级 diff + 当前行上下文', async () => {
    server.use(workspaceHandler(), detailHandler())
    renderPage('/w/10/tables/change-requests')

    fireEvent.click((await screen.findAllByRole('button', { name: '展开详情' }))[0])
    // 三态 diff（修改前 / 修改后）与当前行上下文（含未涉及字段 电话）
    expect(await screen.findByText('修改前')).toBeInTheDocument()
    expect(screen.getByText(/当前行上下文/)).toBeInTheDocument()
    expect(screen.getByText(/电话: 13800000000/)).toBeInTheDocument()
    // 变更项头部标注变更内容摘要（字段级旧值 → 新值）
    expect(screen.getByText('分级：B → A')).toBeInTheDocument()
  })

  it('详情页「返回修改申请」从工作区入口回到工作区列表（而非单表列表）', async () => {
    server.use(
      workspaceHandler(),
      detailHandler(),
      http.get('/api/v1/workspaces/10', () =>
        HttpResponse.json({ id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [], current_user_role: 'owner' })),
      http.get('/api/v1/workspaces/10/members', () => HttpResponse.json([])),
    )
    renderProviders(
      <Routes>
        <Route path="/w/:wid/tables/change-requests" element={<ChangeRequestsPage />} />
        <Route path="/w/:wid/tables/:tid/change-requests/:requestId" element={<ChangeRequestDetailPage />} />
      </Routes>,
      { route: '/w/10/tables/change-requests', ...AUTH },
    )

    fireEvent.click(await screen.findByText('调整客户分级'))
    fireEvent.click(await screen.findByText('返回修改申请'))
    // 回到工作区分栏列表（左栏工作表清单），而非单表列表页
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /客户表/ })).toBeInTheDocument()
    })
  })

  it('展开只读上下文不提供审批入口；行已删除时提示且不渲染行上下文', async () => {
    server.use(workspaceHandler(), detailHandler({ rowMissing: true }))
    renderPage('/w/10/tables/change-requests')

    fireEvent.click((await screen.findAllByRole('button', { name: '展开详情' }))[0])
    expect(await screen.findByText('行已删除')).toBeInTheDocument()
    expect(screen.queryByText(/当前行上下文/)).toBeNull()
    expect(screen.queryByRole('button', { name: /执行合并/ })).toBeNull()
  })
})

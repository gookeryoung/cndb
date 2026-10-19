/**
 * ChangeRequestRowMergePage 冲突处理页测试 —— 冲突字段裁决表 / 未裁决禁提交 /
 * 提交载荷（采用某申请值 / 保留当前值）/ delete 与修改互斥的行级裁决。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import ChangeRequestRowMergePage from './ChangeRequestRowMergePage'
import { renderProviders } from '@/test/render-providers'
import { mockUser, server } from '@/test/msw'
import type { ChangeRequestDetail, CRRowMergePayload } from '@/api'

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }
const LIST = '/api/v1/workspaces/10/tables/20/change-requests'

function detail(id: number, values: Record<string, unknown>, items: ChangeRequestDetail['items'] = []): ChangeRequestDetail {
  return {
    id, workspace_id: 10, table_id: 20, title: `申请 #${id}`, description: '',
    status: 'open', stale: false, submitted_by_id: 2, reviewed_by_id: null,
    reviewed_at: null, review_comment: null,
    created_at: id === 51 ? '2026-10-02T09:00:00' : '2026-10-02T10:00:00',
    updated_at: '2026-10-02T10:00:00',
    items: items.length ? items : [{
      id: 600 + id, op: 'update', row_id: 12,
      base_values: { 数量: 1 }, values, current_values: { 数量: 1 }, field_conflicts: [],
    }],
    actions: [],
  }
}

function setup(opts: {
  group: Record<string, unknown>
  details: Record<number, ChangeRequestDetail>
  captured?: { body?: CRRowMergePayload }
}) {
  server.use(
    http.get(LIST, () => HttpResponse.json({
      groups: [{
        row_values: {}, row_missing: false, conflict_fields: [], drift_fields: [],
        has_conflict: false, has_drift: false, latest_created_at: null, requests: [],
        row_id: 12, ...opts.group,
      }],
      ungrouped: [], total: 1, write_mode: 'change_request',
    })),
    http.get('/api/v1/workspaces/10/tables/20/change-requests/51', () => HttpResponse.json(opts.details[51])),
    http.get('/api/v1/workspaces/10/tables/20/change-requests/52', () => HttpResponse.json(opts.details[52])),
    http.post('/api/v1/workspaces/10/tables/20/change-requests/rows/12/merge', async ({ request }) => {
      if (opts.captured) opts.captured.body = await request.json() as CRRowMergePayload
      return HttpResponse.json({ applied: 2, skipped: 0, merged_request_ids: [51, 52], requests: [] })
    }),
  )
}

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/change-requests/rows/:rowId/merge" element={<ChangeRequestRowMergePage />} />
      <Route path="/w/:wid/tables/:tid/change-requests" element={<div data-testid="cr-list-stub">列表</div>} />
    </Routes>,
    { route: '/w/10/tables/20/change-requests/rows/12/merge?ids=51,52', ...AUTH },
  )
}

describe('ChangeRequestRowMergePage 冲突处理页', () => {
  it('渲染冲突字段裁决表，未裁决时禁用提交，裁决后可提交并携带裁决', async () => {
    const captured: { body?: CRRowMergePayload } = {}
    setup({
      group: { conflict_fields: ['数量'], has_conflict: true, row_values: { 名称: '甲', 数量: 1 } },
      details: {
        51: detail(51, { 数量: 10 }),
        52: detail(52, { 数量: 20 }),
      },
      captured,
    })
    renderPage()

    expect(await screen.findByText('冲突字段裁决')).toBeInTheDocument()
    expect(screen.getByText(/采用 #51 的值/)).toBeInTheDocument()
    expect(screen.getByText(/采用 #52 的值/)).toBeInTheDocument()
    // 未裁决 → 提交按钮禁用，提示待裁决字段
    const submit = screen.getByRole('button', { name: /执行批量合并/ })
    expect(submit).toBeDisabled()
    expect(screen.getByText(/请先裁决冲突字段：数量/)).toBeInTheDocument()

    // 选择「采用 #52 的值」（radio 顺序：51 / 52 / 保留当前）
    fireEvent.click(screen.getAllByRole('radio')[1])
    await waitFor(() => expect(submit).toBeEnabled())
    fireEvent.click(submit)
    await waitFor(() => expect(captured.body?.resolutions?.['数量']).toEqual({ strategy: 'item', item_id: 652 }))
    expect(captured.body?.request_ids).toEqual([51, 52])
  })

  it('保留当前值 → strategy=current', async () => {
    const captured: { body?: CRRowMergePayload } = {}
    setup({
      group: { conflict_fields: ['数量'], has_conflict: true, row_values: { 数量: 1 } },
      details: { 51: detail(51, { 数量: 10 }), 52: detail(52, { 数量: 20 }) },
      captured,
    })
    renderPage()

    await screen.findByText('冲突字段裁决')
    fireEvent.click(screen.getByRole('button', { name: '全部保留当前' }))
    const submit = screen.getByRole('button', { name: /执行批量合并/ })
    await waitFor(() => expect(submit).toBeEnabled())
    fireEvent.click(submit)
    await waitFor(() => expect(captured.body?.resolutions?.['数量']).toEqual({ strategy: 'current' }))
  })

  it('delete 与修改互斥时提供行级操作裁决并随载荷提交', async () => {
    const captured: { body?: CRRowMergePayload } = {}
    setup({
      group: { row_values: {} },
      details: {
        51: detail(51, {}, [{ id: 651, op: 'delete', row_id: 12, base_values: { 数量: 1 }, values: {}, current_values: { 数量: 1 }, field_conflicts: [] }]),
        52: detail(52, { 数量: 20 }),
      },
      captured,
    })
    renderPage()

    expect(await screen.findByText('删除与修改互斥')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /执行删除/ }))
    const submit = screen.getByRole('button', { name: /执行批量合并/ })
    await waitFor(() => expect(submit).toBeEnabled())
    fireEvent.click(submit)
    await waitFor(() => expect(captured.body?.row_action).toBe('delete'))
  })
})

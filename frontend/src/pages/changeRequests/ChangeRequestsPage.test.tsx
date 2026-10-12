/**
 * ChangeRequestsPage 修改申请列表测试 —— scope 筛选 / 状态与冲突/stale 标记 / 点击导航。
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
import type { ChangeRequest } from '@/api'

const CRS: ChangeRequest[] = [
  {
    id: 51, workspace_id: 10, table_id: 20, title: '调整客户分级',
    description: '', status: 'open', stale: true, submitted_by_id: 2,
    reviewed_by_id: null, reviewed_at: null, review_comment: null,
    created_at: '2026-10-02T10:00:00', updated_at: '2026-10-02T10:00:00', conflicts_count: 3,
  },
  {
    id: 50, workspace_id: 10, table_id: 20, title: '清理重复行',
    description: '', status: 'merged', stale: false, submitted_by_id: 1,
    reviewed_by_id: 1, reviewed_at: '2026-10-01T12:00:00', review_comment: null,
    created_at: '2026-10-01T09:00:00', updated_at: '2026-10-01T12:00:00', conflicts_count: 0,
  },
]

const AUTH = { initialAuth: { user: mockUser, token: 'fake' } }

function listHandler(captured: { scope?: string } = {}) {
  return http.get('/api/v1/workspaces/10/tables/20/change-requests', ({ request }) => {
    captured.scope = new URL(request.url).searchParams.get('scope') ?? undefined
    const scope = captured.scope ?? 'open'
    const items = scope === 'all' ? CRS : scope === 'mine' ? CRS.filter(c => c.submitted_by_id === 1) : CRS.filter(c => c.status === 'open')
    return HttpResponse.json({ items, total: items.length })
  })
}

function renderPage(route = '/w/10/tables/20/change-requests') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables/:tid/change-requests" element={<ChangeRequestsPage />} />
      <Route path="/w/:wid/tables/:tid/change-requests/:requestId" element={<div data-testid="cr-detail-stub">详情</div>} />
    </Routes>,
    { route, ...AUTH },
  )
}

describe('ChangeRequestsPage 修改申请列表', () => {
  it('默认展示 open 列表，渲染 stale 与冲突标记', async () => {
    const captured: { scope?: string } = {}
    server.use(listHandler(captured))
    renderPage()

    expect(await screen.findByText('调整客户分级')).toBeInTheDocument()
    // open 视图不显示状态 Tag（全部开放），merged 项不出现
    expect(screen.queryByText('清理重复行')).toBeNull()
    expect(screen.getByText('基准已过期')).toBeInTheDocument()
    expect(screen.getByText('与 3 行在途申请冲突')).toBeInTheDocument()
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

  it('点击列表项导航到详情页', async () => {
    server.use(listHandler())
    renderPage()

    fireEvent.click(await screen.findByText('调整客户分级'))
    await waitFor(() => {
      expect(screen.getByTestId('cr-detail-stub')).toBeInTheDocument()
    })
  })

  it('新建按钮提示走网格编辑双轨路径', async () => {
    server.use(listHandler())
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*修\s*改\s*申\s*请/ }))
    // 引导文案（message.info portal）
    expect(await screen.findByText('请直接在表格中编辑数据，系统会自动生成修改申请')).toBeInTheDocument()
  })
})

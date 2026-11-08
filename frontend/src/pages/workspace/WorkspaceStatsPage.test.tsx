/** WorkspaceStatsPage 测试 —— 一级导航「统计」页（/w/:wid/stats）. */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { screen, within } from '@testing-library/react'
import WorkspaceStatsPage from './WorkspaceStatsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

function setupWorkspaceDetailHandler(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get('/api/v1/workspaces/:wid', () =>
      HttpResponse.json({
        id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
        owner: { id: 1, username: 'alice', nickname: null },
        table_count: 3, member_count: 5, view_count: 4, total_rows: 120,
        document_count: 8, design_count: 2,
        storage_bytes: 1024 * 1024, storage_quota_bytes: 2 * 1024 * 1024,
        current_user_role: 'owner',
        ...overrides,
      }),
    ),
  )
}

function renderPage(initialPath = '/w/10/stats') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/stats" element={<WorkspaceStatsPage />} />
    </Routes>,
    { route: initialPath },
  )
}

describe('WorkspaceStatsPage 工作区统计页', () => {
  it('默认展示统计概览与存储用量', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    // 等待详情查询返回（存储条文本是数据载入完成的信号）
    await screen.findByText('1.0 MB / 2.0 MB')
    const stats = within(screen.getByTestId('ws-stats-grid'))
    expect(stats.getByText('数据表')).toBeInTheDocument()
    expect(stats.getByText('视图')).toBeInTheDocument()
    expect(stats.getByText('数据行')).toBeInTheDocument()
    expect(stats.getByText('文档')).toBeInTheDocument()
    expect(stats.getByText('设计')).toBeInTheDocument()
    expect(stats.getByText('成员')).toBeInTheDocument()

    const cardText = (label: string) =>
      stats.getByText(label).parentElement?.parentElement?.textContent ?? ''
    expect(cardText('数据表')).toContain('3')
    expect(cardText('文档')).toContain('8')
    expect(cardText('设计')).toContain('2')
    expect(cardText('成员')).toContain('5')

    expect(screen.getByText('存储用量')).toBeInTheDocument()
  })

  it('未启用的模块不展示对应统计卡片（tables-only 工作区）', async () => {
    setupWorkspaceDetailHandler({ modules: ['tables'] })
    renderPage()

    await screen.findByText('1.0 MB / 2.0 MB')
    const stats = within(screen.getByTestId('ws-stats-grid'))
    expect(stats.getByText('数据表')).toBeInTheDocument()
    expect(stats.queryByText('文档')).not.toBeInTheDocument()
    expect(stats.queryByText('设计')).not.toBeInTheDocument()
  })
})

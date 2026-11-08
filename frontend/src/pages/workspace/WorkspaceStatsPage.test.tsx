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

const CONTRIBUTION_ITEMS = [
  {
    user_id: 1, username: 'alice', nickname: 'Alice', role: 'owner',
    is_member: true, is_former_editor: false,
    rows_created: 5, rows_updated: 2, documents_created: 1, documents_edited: 3,
    designs_created: 0, designs_edited: 0, total: 11,
    last_active_at: '2026-01-05T10:00:00',
  },
  {
    user_id: 2, username: 'bob', nickname: 'Bob', role: 'viewer',
    is_member: true, is_former_editor: true,
    rows_created: 0, rows_updated: 2, documents_created: 1, documents_edited: 0,
    designs_created: 1, designs_edited: 0, total: 4,
    last_active_at: '2026-01-04T09:00:00',
  },
  {
    user_id: 3, username: 'carol', nickname: 'Carol', role: null,
    is_member: false, is_former_editor: true,
    rows_created: 0, rows_updated: 0, documents_created: 0, documents_edited: 0,
    designs_created: 1, designs_edited: 1, total: 2,
    last_active_at: '2026-01-03T09:00:00',
  },
]

function setupContributionHandler(
  items = CONTRIBUTION_ITEMS,
  status = 200,
) {
  server.use(
    http.get('/api/v1/workspaces/:wid/stats/contributions', () => {
      if (status !== 200) return HttpResponse.json({ detail: 'boom' }, { status })
      return HttpResponse.json({
        generated_at: '2026-11-08T12:00:00',
        items,
      })
    }),
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

  it('概览展示工作区只读信息，不再展示角色信息板块', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    await screen.findByText('1.0 MB / 2.0 MB')
    expect(screen.getByText('工作区信息（只读）')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('成员可见（仅工作区成员可访问）')).toBeInTheDocument()
    // 2026-11-08 用户口径：移除角色信息板块
    expect(screen.queryByText('角色信息')).not.toBeInTheDocument()
    expect(screen.queryByText('您的角色')).not.toBeInTheDocument()
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

  it('?section=contribution 按编辑者展示贡献，含曾为编辑者与已移出成员', async () => {
    setupWorkspaceDetailHandler()
    setupContributionHandler()
    renderPage('/w/10/stats?section=contribution')

    expect(screen.getByTestId('ws-stats-contribution')).toBeInTheDocument()
    expect(await screen.findByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
    expect(screen.getByText('Carol')).toBeInTheDocument()
    // 当前角色 / 曾为编辑者 / 已移出
    expect(screen.getByText('所有者')).toBeInTheDocument()
    expect(screen.getByText('查看者')).toBeInTheDocument()
    expect(screen.getByText('已移出')).toBeInTheDocument()
    expect(screen.getAllByText('曾为编辑者')).toHaveLength(2)
    // 计数与合计（数字使用 toLocaleString）
    expect(screen.getByText('合计')).toBeInTheDocument()
    expect(screen.getByText('11')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
    // 历史行归属提示
    expect(screen.getByText(/数据行贡献自本版本起统计/)).toBeInTheDocument()
    expect(screen.queryByTestId('ws-stats-grid')).not.toBeInTheDocument()
  })

  it('贡献统计按启用模块隐藏数据行 / 文档 / 设计列', async () => {
    setupWorkspaceDetailHandler({ modules: ['tables'] })
    setupContributionHandler()
    renderPage('/w/10/stats?section=contribution')

    await screen.findByText('Alice')
    expect(screen.getByText('数据行新建')).toBeInTheDocument()
    expect(screen.queryByText('文档新建')).not.toBeInTheDocument()
    expect(screen.queryByText('设计新建')).not.toBeInTheDocument()
    expect(screen.queryByText('文档保存')).not.toBeInTheDocument()
  })

  it('贡献统计空数据显示空态', async () => {
    setupWorkspaceDetailHandler()
    setupContributionHandler([])
    renderPage('/w/10/stats?section=contribution')

    expect(await screen.findByText('暂无贡献数据')).toBeInTheDocument()
  })

  it('贡献统计接口失败显示错误提示', async () => {
    setupWorkspaceDetailHandler()
    setupContributionHandler(CONTRIBUTION_ITEMS, 500)
    renderPage('/w/10/stats?section=contribution')

    expect(await screen.findByText('贡献统计加载失败')).toBeInTheDocument()
  })

  it('未知 section 回落概览分项', async () => {
    setupWorkspaceDetailHandler()
    renderPage('/w/10/stats?section=unknown')

    await screen.findByText('1.0 MB / 2.0 MB')
    expect(screen.getByTestId('ws-stats-grid')).toBeInTheDocument()
    expect(screen.queryByTestId('ws-stats-contribution')).not.toBeInTheDocument()
  })
})

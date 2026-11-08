/**
 * WorkspaceSettingsPage 页面组件测试 —— 工作区设置页.
 *
 * 导航职责已由 MainLayout 分页 tab 承担：页面仅渲染设置内容，
 * 不再包含面包屑、标题行与返回按钮。
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import { screen } from '@testing-library/react'
import WorkspaceSettingsPage from './WorkspaceSettingsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

function setupWorkspaceDetailHandler() {
  server.use(
    http.get('/api/v1/workspaces/:wid', () =>
      HttpResponse.json({
        id: 10, name: '测试工作区', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
        owner: { id: 1, username: 'alice', nickname: null },
        table_count: 0, member_count: 1, view_count: 0, total_rows: 0,
        current_user_role: 'owner',
      }),
    ),
    http.get('/api/v1/workspaces/:wid/members', () => HttpResponse.json([])),
  )
}

function renderPage(initialPath = '/w/10/settings') {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/settings" element={<WorkspaceSettingsPage />} />
    </Routes>,
    { route: initialPath },
  )
}

describe('WorkspaceSettingsPage 工作区设置页', () => {
  it('默认渲染「基本设置」分项内容（分项导航由 MainLayout 侧栏承担）', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    expect(await screen.findByTestId('ws-settings-section-basic')).toBeVisible()
    expect(await screen.findByLabelText('工作区名称')).toBeVisible()
  })

  it('不再渲染面包屑、页内标题、返回按钮与页内 Tabs', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    expect(await screen.findByTestId('ws-settings-section-basic')).toBeVisible()
    expect(screen.queryByTestId('settings-back-btn')).toBeNull()
    // 面包屑（含工作区名的链接）不再渲染
    expect(screen.queryByRole('navigation')).toBeNull()
    // 分项导航在侧栏，页内不再重复渲染 Tabs
    expect(document.querySelector('.ant-tabs')).toBeNull()
  })

  it('已下线的 ?section=stats 回落基本设置，并在顶部展示统计概览', async () => {
    setupWorkspaceDetailHandler()
    renderPage('/w/10/settings?section=stats')

    expect(await screen.findByTestId('ws-settings-section-basic')).toBeVisible()
    expect(await screen.findByTestId('ws-stats-grid')).toBeVisible()
  })

  it('未知分项回落到基本设置', async () => {
    setupWorkspaceDetailHandler()
    renderPage('/w/10/settings?section=unknown')

    expect(await screen.findByTestId('ws-settings-section-basic')).toBeVisible()
  })
})

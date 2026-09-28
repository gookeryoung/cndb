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
  it('仅渲染设置内容（WorkspaceSettingsContent 的基本设置 Tab）', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    expect(await screen.findByText('基本设置')).toBeVisible()
  })

  it('不再渲染面包屑、页内标题与返回按钮（导航由分页 tab 承担）', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    expect(await screen.findByText('基本设置')).toBeVisible()
    expect(screen.queryByTestId('settings-back-btn')).toBeNull()
    // 面包屑（含工作区名的链接）不再渲染
    expect(screen.queryByRole('navigation')).toBeNull()
  })
})

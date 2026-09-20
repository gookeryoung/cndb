/**
 * WorkspaceSettingsPage 页面组件测试 —— 工作区设置独立页.
 *
 * 覆盖：标题与返回按钮渲染 / 面包屑显示工作区名 / 返回按钮跳转表列表。
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import WorkspaceSettingsPage from './WorkspaceSettingsPage'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}</span>
}

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
      <Route path="/w/:wid/tables" element={<LocationProbe />} />
    </Routes>,
    { route: initialPath },
  )
}

describe('WorkspaceSettingsPage 工作区设置页', () => {
  it('渲染标题、返回按钮，并加载设置内容', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    expect(screen.getByText('工作区设置')).toBeInTheDocument()
    expect(screen.getByTestId('settings-back-btn')).toBeInTheDocument()
    // 设置内容挂载（WorkspaceSettingsContent 的基本设置 Tab）
    expect(await screen.findByText('基本设置')).toBeVisible()
  })

  it('面包屑显示工作区名称（异步加载后）', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    expect(await screen.findByText('测试工作区')).toBeInTheDocument()
  })

  it('点击返回按钮跳转到 /w/:wid/tables', async () => {
    setupWorkspaceDetailHandler()
    renderPage()

    await waitFor(() => expect(screen.getByTestId('settings-back-btn')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('settings-back-btn'))
    expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables')
  })
})

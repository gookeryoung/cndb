/**
 * WorkspaceSettingsContent 组件测试 —— 覆盖删除工作区后的路由跳转行为。
 *
 * 验收：
 *   删除工作区成功后，应自动 navigate('/w', { replace: true }) 回到工作区列表。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, fireEvent, render } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import WorkspaceSettingsContent from './WorkspaceSettingsContent'
import { createTestQueryClient } from '@/test/render-providers'
import { server } from '@/test/msw'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { useAuthStore } from '@/store/auth'
import { workspaceApi } from '@/api'

/** Location 探针 —— 读取当前 pathname 供断言跳转 */
function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}</span>
}

const WID = '10'

function setupWorkspaceHandlers() {
  server.use(
    http.get('/api/v1/workspaces/:wid', () =>
      HttpResponse.json({
        id: 10, name: '测试', description: '', visibility: 'member', tags: [],
        allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
        owner: { id: 1, username: 'alice', nickname: null },
        table_count: 0, member_count: 1, view_count: 0, total_rows: 0,
        current_user_role: 'owner',
      }),
    ),
    http.get('/api/v1/workspaces/:wid/members', () =>
      HttpResponse.json([
        { id: 1, workspace_id: 10, user_id: 1, role: 'owner', pinned: false,
          user: { id: 1, username: 'alice', nickname: null, email: null } },
      ]),
    ),
    http.get('/api/v1/workspaces/:wid/members/candidates', () =>
      HttpResponse.json({ results: [] }),
    ),
  )
}

describe('WorkspaceSettingsContent 删除路由跳转', () => {
  beforeEach(() => {
    setupWorkspaceHandlers()
    useAuthStore.setState({
      user: { id: 1, username: 'alice', email: null, role: 'system_admin', is_active: true },
      token: 'fake-token', loading: false,
    })
  })

  it('owner 删除工作区成功后 navigate 到 /w', async () => {
    const removeSpy = vi.spyOn(workspaceApi, 'remove').mockResolvedValue(undefined as never)
    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <MemoryRouter
            future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
            initialEntries={[`/w/${WID}/settings`]}
          >
            <Routes>
              <Route path="/w" element={<LocationProbe />} />
              <Route path="/w/:wid/settings" element={<WorkspaceSettingsContent wid={WID} />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>,
    )

    // 等待基本设置 Tab 出现
    await waitFor(() => expect(screen.getByText('基本设置')).toBeVisible())

    // 切换到「统计信息」Tab（危险操作区在此）
    fireEvent.click(screen.getByText('统计信息'))
    await waitFor(() => expect(screen.getByText('危险操作')).toBeVisible())

    // 点击删除按钮触发 Popconfirm
    const deleteBtn = screen.getByRole('button', { name: /删除工作区/ })
    fireEvent.click(deleteBtn)

    // 等待 Popconfirm overlay
    await waitFor(() => {
      expect(document.querySelector('.ant-popconfirm')).not.toBeNull()
    }, { timeout: 5000 })

    // 点击确认按钮（okType='danger'）
    const confirmBtn = document.querySelector('.ant-popconfirm .ant-btn-dangerous, .ant-popconfirm .ant-btn-primary')!
    fireEvent.click(confirmBtn)

    // 等删除 mutation 被调用
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith(WID), { timeout: 5000 })

    // navigate 执行后 LocationProbe 应渲染
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/w')
    }, { timeout: 5000 })

    removeSpy.mockRestore()
  })
})

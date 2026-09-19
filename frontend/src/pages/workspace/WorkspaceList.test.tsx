/**
 * WorkspaceList 组件测试 —— 覆盖创建工作区后的路由跳转行为。
 *
 * 验收：
 *   新建工作区成功后，应自动跳转到新工作区的表列表页 `/w/<id>/tables`。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, fireEvent, render } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import WorkspaceList from './WorkspaceList'
import { createTestQueryClient } from '@/test/render-providers'
import { server } from '@/test/msw'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { useAuthStore } from '@/store/auth'
import type { Workspace } from '@/api'

/** Location 探针 —— 读取当前 pathname 供断言跳转 */
function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}</span>
}

/** 构造完整 Provider 栈 + 路由 */
function renderWorkspaceList(initialRoute = '/w') {
  useAuthStore.setState({
    user: { id: 1, username: 'alice', email: null, role: 'system_admin', is_active: true },
    token: 'fake-token',
    loading: false,
  })
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MemoryRouter
          future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
          initialEntries={[initialRoute]}
        >
          <Routes>
            <Route path="/w" element={<WorkspaceList />} />
            <Route path="/w/:wid/tables" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('WorkspaceList 路由跳转', () => {
  beforeEach(() => {
    // 创建工作区 API handler —— 返回带 id=42 的新工作区
    server.use(
      http.post('/api/v1/workspaces', async ({ request }) => {
        const body = (await request.json()) as Partial<Workspace>
        return HttpResponse.json({
          id: 42,
          name: body.name ?? '新工作区',
          description: body.description ?? '',
          visibility: body.visibility ?? 'member',
          tags: body.tags ?? [],
          allow_edit: body.allow_edit ?? true,
          created_by_id: 1,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
      }),
    )
  })

  it('创建工作区成功后跳转到 /w/<新id>/tables', async () => {
    renderWorkspaceList()

    // 等待列表加载完成
    await waitFor(() => {
      expect(screen.getByTestId('create-workspace-btn')).toBeVisible()
    })

    // 打开创建对话框
    fireEvent.click(screen.getByTestId('create-workspace-btn'))
    await waitFor(() => {
      expect(screen.getByTestId('create-workspace-modal')).toBeVisible()
    })

    // 填写名称（唯一必填字段）
    fireEvent.change(screen.getByLabelText('工作区名称'), {
      target: { value: '产品研发部' },
    })

    // 点击 OK 按钮（antd Modal okText='创建' —— 通过 data-testid + 主按钮过滤）
    const okBtn = document.querySelector(
      '.ant-modal-confirm-btns .ant-btn-primary, .ant-modal-footer .ant-btn-primary',
    ) as HTMLElement | null
    expect(okBtn).not.toBeNull()
    fireEvent.click(okBtn!)

    // 等待 navigate 执行 + LocationProbe 渲染
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/w/42/tables')
    }, { timeout: 3000 })
  })
})

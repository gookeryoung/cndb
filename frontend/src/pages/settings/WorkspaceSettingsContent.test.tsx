/**
 * WorkspaceSettingsContent 组件测试 —— 覆盖删除工作区后的路由跳转行为。
 *
 * 验收：
 *   删除工作区成功后，应自动 navigate('/w', { replace: true }) 回到工作区列表。
 *
 * 追加覆盖：Tab 切换与统计渲染 / 保存设置成功-失败-校验拦截 /
 * 成员管理（添加成员 / 修改角色 / 移除成员）/ 编辑权限开关 /
 * viewer 只读权限分支 / admin 权限边界。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { message } from 'antd'
import { screen, waitFor, fireEvent, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { within } from '@testing-library/react'
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
        {
          id: 1, workspace_id: 10, user_id: 1, role: 'owner', pinned: false,
          user: { id: 1, username: 'alice', nickname: null, email: null }
        },
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

// ─────────────── Tab 渲染 / 保存 / 成员管理 / 权限分支 ───────────────

/** 成员 fixtures：owner（当前用户 alice）+ editor（carol） */
const MEMBERS = [
  {
    id: 1, workspace_id: 10, user_id: 1, role: 'owner', pinned: false,
    user: { id: 1, username: 'alice', nickname: null, email: 'alice@example.com' }
  },
  {
    id: 3, workspace_id: 10, user_id: 5, role: 'editor', pinned: false,
    user: { id: 5, username: 'carol', nickname: null, email: null }
  },
]

/** 按角色渲染设置内容（detail.current_user_role 决定权限分支） */
function renderContent(role: 'owner' | 'admin' | 'viewer' = 'owner') {
  server.use(
    http.get('/api/v1/workspaces/10', () =>
      HttpResponse.json({
        id: 10, name: '测试', description: '', visibility: 'member', tags: ['研发'],
        allow_edit: true, created_by_id: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '',
        owner: { id: 1, username: 'alice', nickname: null },
        table_count: 3, member_count: 2, view_count: 2, total_rows: 120,
        current_user_role: role,
      })),
    http.get('/api/v1/workspaces/10/members', () => HttpResponse.json(MEMBERS)),
    http.get('/api/v1/workspaces/10/members/candidates', () =>
      HttpResponse.json({ results: [{ id: 9, username: 'eve', email: 'eve@example.com' }] })),
  )
  const queryClient = createTestQueryClient()
  useAuthStore.setState({
    user: { id: 1, username: 'alice', email: null, role: 'system_admin', is_active: true },
    token: 'fake-token', loading: false,
  })
  return render(
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
}

/** 等待工作区详情加载完成 —— 表单回填后才会解除禁用，避免用例与查询竞态 */
async function waitDetailLoaded() {
  await screen.findByDisplayValue('测试')
}

/**
 * 监听 antd 静态 message（success/error），返回两个 spy.
 *
 * 静态 message 容器是模块级单例：同文件前序用例触发过 message 后，
 * setup.ts 的 afterEach 会把 .ant-message 节点摘出 DOM，后续 message
 * 全部写入游离节点，DOM 文本断言不可靠 —— 因此改用 spy 断言调用参数。
 * vite 配置 restoreMocks: true，用例结束后自动还原。
 */
function spyToast() {
  return {
    success: vi.spyOn(message, 'success'),
    error: vi.spyOn(message, 'error'),
  }
}

describe('WorkspaceSettingsContent 基本设置与保存', () => {
  it('修改名称后保存发起 PATCH 并提示设置已保存', async () => {
    let patched: Record<string, unknown> | undefined
    server.use(
      http.patch('/api/v1/workspaces/10', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 10 })
      }),
    )
    const toast = spyToast()
    renderContent()
    await waitDetailLoaded()

    const nameInput = screen.getByLabelText('工作区名称') as HTMLInputElement
    expect(nameInput.value).toBe('测试')

    const user = userEvent.setup()
    await user.clear(nameInput)
    await user.type(nameInput, '新名称')
    await user.click(screen.getByRole('button', { name: '保存设置' }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('设置已保存'))
    expect(patched).toMatchObject({ name: '新名称' })
  })

  it('保存失败时提示后端错误信息', async () => {
    server.use(
      http.patch('/api/v1/workspaces/10', () =>
        HttpResponse.json({ detail: '名称与已有工作区重复' }, { status: 409 })),
    )
    const toast = spyToast()
    renderContent()
    await waitDetailLoaded()

    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('名称与已有工作区重复'))
  })

  it('名称清空后保存被必填校验拦截且不发起 PATCH', async () => {
    let patchCount = 0
    server.use(
      http.patch('/api/v1/workspaces/10', () => {
        patchCount += 1
        return HttpResponse.json({ id: 10 })
      }),
    )
    renderContent()
    await waitDetailLoaded()

    const nameInput = screen.getByLabelText('工作区名称')
    const user = userEvent.setup()
    await user.clear(nameInput)
    await user.click(screen.getByRole('button', { name: '保存设置' }))

    expect(await screen.findByText('请输入名称')).toBeInTheDocument()
    // 等一拍确认没有发起 PATCH
    await waitFor(() => expect(patchCount).toBe(0))
  })
})

describe('WorkspaceSettingsContent 统计信息 Tab', () => {
  it('渲染统计卡片与角色信息，owner 可见危险操作区', async () => {
    renderContent('owner')

    fireEvent.click(await screen.findByText('统计信息'))

    expect(await screen.findByText('危险操作')).toBeInTheDocument()
    expect(screen.getByText('角色信息')).toBeInTheDocument()
    expect(screen.getByText('数据表')).toBeInTheDocument()
    expect(screen.getByText('数据行')).toBeInTheDocument()
  })
})

describe('WorkspaceSettingsContent 成员管理（owner）', () => {
  it('编辑权限开关切换后发起 allow_edit 更新', async () => {
    let patched: Record<string, unknown> | undefined
    server.use(
      http.patch('/api/v1/workspaces/10', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 10 })
      }),
    )
    const toast = spyToast()
    renderContent('owner')
    await waitDetailLoaded()

    fireEvent.click(screen.getByText('权限'))
    const sw = await screen.findByRole('switch')
    expect(sw).toBeEnabled()

    fireEvent.click(sw)

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('编辑权限已更新'))
    expect(patched).toMatchObject({ allow_edit: false })
  })

  it('添加成员：搜索选择候选用户后发起 POST 并提示已添加成员', async () => {
    let postBody: Record<string, unknown> | undefined
    server.use(
      http.post('/api/v1/workspaces/10/members', async ({ request }) => {
        postBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 9, role: 'editor' })
      }),
    )
    const toast = spyToast()
    renderContent('owner')
    await waitDetailLoaded()

    fireEvent.click(screen.getByText('权限'))
    fireEvent.click(await screen.findByRole('button', { name: /添\s*加\s*成\s*员/ }))

    // 添加成员弹窗打开（标题断言，避免与"添加成员"入口按钮重名）
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('添加成员'))
    const modal = document.querySelector('.ant-modal-content') as HTMLElement
    const okBtn = within(modal).getByRole('button', { name: /^添\s*加$/ })
    expect(okBtn).toBeDisabled()

    // 弹窗内第一个 combobox 是用户搜索 Select；'eve' 同时命中 rc-select 的
    // aria-live 副本与选项 label 的 <strong>，用 selector 限定后者（点击后冒泡选中）
    fireEvent.mouseDown(within(modal).getAllByRole('combobox')[0]!)
    fireEvent.click(await screen.findByText('eve', { selector: 'strong' }))
    // 每次轮询重新查询按钮节点，避免 re-render 替换节点导致旧引用失真
    await waitFor(() => expect(within(modal).getByRole('button', { name: /^添\s*加$/ })).toBeEnabled())

    fireEvent.click(within(modal).getByRole('button', { name: /^添\s*加$/ }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('已添加成员'))
    expect(postBody).toMatchObject({ username: 'eve', role: 'editor' })
  })

  it('修改成员角色：下拉选择管理员后发起 PATCH 并提示角色已更新', async () => {
    let patched: Record<string, unknown> | undefined
    server.use(
      http.patch('/api/v1/workspaces/10/members/3', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 3, role: 'admin' })
      }),
    )
    const toast = spyToast()
    renderContent('owner')
    await waitDetailLoaded()

    fireEvent.click(screen.getByText('权限'))

    // carol（editor）的角色 Select —— owner 可管理；未开弹窗时它是唯一可访问的 combobox。
    // optionRender 把角色名渲染在内层 div（直接文本节点），点击后冒泡到选项节点完成选中
    fireEvent.mouseDown(await screen.findByRole('combobox'))
    fireEvent.click(await screen.findByText('管理员'))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('角色已更新'))
    expect(patched).toMatchObject({ role: 'admin' })
  })

  it('移除成员：Popconfirm 确认后发起 DELETE 并提示已移除成员', async () => {
    let deleteCalled = false
    server.use(
      http.delete('/api/v1/workspaces/10/members/3', () => {
        deleteCalled = true
        return HttpResponse.json({})
      }),
    )
    const toast = spyToast()
    renderContent('owner')
    await waitDetailLoaded()

    fireEvent.click(screen.getByText('权限'))

    // carol 行的移除按钮（图标按钮，danger 样式）
    const removeBtn = await waitFor(() => {
      const btn = document.querySelector('button.ant-btn-dangerous')
      expect(btn).not.toBeNull()
      return btn as HTMLElement
    })
    fireEvent.click(removeBtn)

    // Popconfirm 确认
    await waitFor(() => expect(document.querySelector('.ant-popconfirm')).not.toBeNull())
    fireEvent.click(document.querySelector('.ant-popconfirm .ant-btn-primary')!)

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('已移除成员'))
    expect(deleteCalled).toBe(true)
  })
})

describe('WorkspaceSettingsContent 权限分支', () => {
  it('viewer：表单只读提示、无保存按钮、成员管理受限、无危险操作区', async () => {
    renderContent('viewer')

    // 基本设置 Tab：只读提示 + 无保存按钮
    expect(await screen.findByText(/您的角色（查看者）仅能查看设置，无法修改/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存设置' })).not.toBeInTheDocument()

    // 权限 Tab：提示无权管理、无添加成员按钮、角色为纯 Tag 展示
    fireEvent.click(screen.getByText('权限'))
    expect(await screen.findByText('仅管理员及以上角色可管理成员与权限')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /添\s*加\s*成\s*员/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByText('编辑者')).toBeInTheDocument()

    // 编辑权限开关禁用
    expect(screen.getByRole('switch')).toBeDisabled()

    // 统计 Tab：无危险操作区
    fireEvent.click(screen.getByText('统计信息'))
    await waitFor(() => expect(screen.getByText('角色信息')).toBeVisible())
    expect(screen.queryByText('危险操作')).not.toBeInTheDocument()
  })

  it('admin：可保存设置与管理成员，但无删除工作区权限', async () => {
    renderContent('admin')
    await waitDetailLoaded()

    // 基本设置：admin 可编辑 → 有保存按钮
    expect(screen.getByRole('button', { name: '保存设置' })).toBeInTheDocument()

    // 权限 Tab：可添加成员，但 owner 卡片无"转让所有权"（仅 owner 可见）
    fireEvent.click(screen.getByText('权限'))
    expect(await screen.findByRole('button', { name: /添\s*加\s*成\s*员/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /转\s*让\s*所\s*有\s*权/ })).not.toBeInTheDocument()

    // 统计 Tab：admin 不可见危险操作区
    fireEvent.click(screen.getByText('统计信息'))
    await waitFor(() => expect(screen.getByText('角色信息')).toBeVisible())
    expect(screen.queryByText('危险操作')).not.toBeInTheDocument()
  })
})

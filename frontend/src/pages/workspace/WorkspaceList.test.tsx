/**
 * WorkspaceList 组件测试 —— 覆盖创建工作区后的路由跳转行为。
 *
 * 验收：
 *   新建工作区成功后，应自动跳转到新工作区的表列表页 `/w/<id>/tables`。
 *
 * 追加覆盖：加载态 / 空列表空态 / 搜索过滤与无匹配空态 / 点击卡片进入工作区 /
 * 置顶请求 / 创建弹窗名称校验 / 创建失败错误提示 / 编辑已关闭标记。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { screen, waitFor, fireEvent, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

// ─────────────── 列表渲染 / 搜索 / 进入工作区 / 置顶 / 创建分支 ───────────────

/** 构造带统计信息的工作区卡片数据 */
function makeWs(overrides: Partial<Workspace> & { id: number; name: string }): Workspace {
  return {
    description: '', visibility: 'member', tags: [], allow_edit: true,
    created_by_id: 1, created_at: '', updated_at: '',
    ...overrides,
  }
}

describe('WorkspaceList 列表渲染与交互', () => {
  it('列表请求未返回时显示加载中', async () => {
    server.use(
      http.get('/api/v1/workspaces', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    renderWorkspaceList()

    expect(await screen.findByText('加载中...')).toBeInTheDocument()
  })

  it('空列表显示创建引导空态', async () => {
    server.use(http.get('/api/v1/workspaces', () => HttpResponse.json([])))
    renderWorkspaceList()

    expect(await screen.findByText('还没有工作区，创建一个吧！')).toBeInTheDocument()
  })

  it('搜索关键字过滤卡片，无匹配时显示搜索空态', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([
          makeWs({ id: 10, name: '产品研发', description: '核心业务数据' }),
          makeWs({ id: 11, name: '市场运营', description: '客户数据', tags: ['增长'] }),
        ])),
    )
    renderWorkspaceList()

    expect(await screen.findByText('产品研发')).toBeInTheDocument()
    const input = screen.getByPlaceholderText('搜索工作区名称/标签...')

    // 按名称过滤：市场运营卡片消失
    await userEvent.type(input, '产品')
    await waitFor(() => expect(screen.queryByText('市场运营')).not.toBeInTheDocument())
    expect(screen.getByText('产品研发')).toBeInTheDocument()

    // 标签也能命中
    await userEvent.clear(input)
    await userEvent.type(input, '增长')
    expect(await screen.findByText('市场运营')).toBeInTheDocument()

    // 无匹配 → 搜索空态
    await userEvent.clear(input)
    await userEvent.type(input, '不存在关键字')
    expect(await screen.findByText('没有匹配「不存在关键字」的工作区')).toBeInTheDocument()
  })

  it('点击卡片主体进入该工作区的表列表页', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({
          id: 10, name: '测试工作区', allow_edit: false, current_user_role: 'owner',
          table_count: 3, member_count: 5,
        })])),
    )
    renderWorkspaceList()

    expect(await screen.findByText('测试工作区')).toBeInTheDocument()
    // allow_edit=false 的卡片展示"编辑已关闭"标记
    expect(screen.getByText('编辑已关闭')).toBeInTheDocument()

    // 点击卡片主体（非底部操作区）→ 跳转
    const user = userEvent.setup()
    await user.click(screen.getByText('测试工作区'))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables'))
  })

  it('点击置顶发起 togglePin 请求', async () => {
    let pinBody: Record<string, unknown> | undefined
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({ id: 10, name: '测试工作区' })])),
      http.post('/api/v1/workspaces/pin', async ({ request }) => {
        pinBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ pinned: true })
      }),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    await user.click(await screen.findByText('置顶'))

    await waitFor(() => expect(pinBody).toMatchObject({ workspace_id: 10 }))
  })
})

describe('WorkspaceList 创建弹窗校验与失败分支', () => {
  /** 打开创建弹窗并返回 OK 按钮 */
  async function openCreateModal() {
    renderWorkspaceList()
    await waitFor(() => expect(screen.getByTestId('create-workspace-btn')).toBeVisible())
    fireEvent.click(screen.getByTestId('create-workspace-btn'))
    await waitFor(() => expect(screen.getByTestId('create-workspace-modal')).toBeVisible())
    return document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement
  }

  it('名称为空时提交被拦并提示请输入名称', async () => {
    const okBtn = await openCreateModal()

    fireEvent.click(okBtn)

    expect(await screen.findByText('请输入名称')).toBeInTheDocument()
  })

  it('创建失败时提示后端错误信息且弹窗不关闭', async () => {
    server.use(
      http.post('/api/v1/workspaces', () =>
        HttpResponse.json({ detail: '工作区数量已达上限' }, { status: 500 })),
    )
    const okBtn = await openCreateModal()
    fireEvent.change(screen.getByLabelText('工作区名称'), { target: { value: '新产品线' } })
    fireEvent.click(okBtn)

    expect(await screen.findByText('工作区数量已达上限')).toBeInTheDocument()
    // 失败后弹窗仍打开（可修正后重试）
    expect(screen.getByTestId('create-workspace-modal')).toBeInTheDocument()
  })
})

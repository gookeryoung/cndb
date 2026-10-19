/**
 * WorkspaceList 组件测试 —— 覆盖创建工作区后的路由跳转行为。
 *
 * 验收：
 *   新建工作区成功后，应自动跳转到新工作区的表列表页 `/w/<id>/tables`。
 *
 * 追加覆盖：加载态 / 空列表空态 / 搜索过滤与无匹配空态 / 点击卡片进入工作区 /
 * 置顶请求 / 创建弹窗名称校验 / 创建失败错误提示 / 编辑已关闭标记。
 */

import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { screen, waitFor, fireEvent, render, within } from '@testing-library/react'
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
            <Route path="/w/:wid/documents" element={<LocationProbe />} />
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
    created_at: '', updated_at: '',
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

// ─────────────── 移动端适配：工具栏堆叠 + Modal 宽度 ───────────────
// 回归背景：工具栏搜索框固定 260px 且按钮行不换行，375px 视口下页面横向溢出。

/** 临时覆盖 jsdom 视口宽度（useResponsive 挂载时读取 innerWidth 判定断点） */
function setViewportWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true, writable: true })
}

/** 移除自有属性覆盖，还原 jsdom 原型上的 innerWidth getter */
function restoreViewport() {
  delete (window as unknown as { innerWidth?: number }).innerWidth
}

/** 获取搜索框外层容器（Input.Search 的 style 落在 group wrapper 上） */
function getSearchWrapper(): HTMLElement {
  const input = screen.getByPlaceholderText('搜索工作区名称/标签...')
  return input.closest('.ant-input-group-wrapper') as HTMLElement
}

describe('WorkspaceList 移动端适配', () => {
  afterEach(restoreViewport)

  it('移动端（375px）工具栏纵向堆叠，搜索框占满整行且按钮均分宽度', () => {
    setViewportWidth(375)
    renderWorkspaceList()

    // 工具栏改为纵向排列，子项拉伸占满
    expect(screen.getByTestId('workspace-list-toolbar')).toHaveStyle({ flexDirection: 'column' })
    expect(screen.getByTestId('workspace-list-toolbar')).toHaveStyle({ alignItems: 'stretch' })

    // 搜索框不再固定 260px，占满整行（消除横向溢出的主因）
    expect(getSearchWrapper()).toHaveStyle({ width: '100%' })

    // 两个操作按钮均分剩余宽度
    expect(screen.getByTestId('create-workspace-btn')).toHaveStyle({ flex: '1 1 0%' })
    expect(screen.getByTestId('import-workspace-btn')).toHaveStyle({ flex: '1 1 0%' })
  })

  it('移动端创建弹窗宽度收窄为视口宽度减边距，不再固定 520px', async () => {
    setViewportWidth(375)
    renderWorkspaceList()

    fireEvent.click(screen.getByTestId('create-workspace-btn'))
    await screen.findByTestId('create-workspace-modal')

    const modal = document.querySelector('.ant-modal') as HTMLElement
    expect(modal).not.toBeNull()
    expect(modal.style.width).toBe('calc(100vw - 32px)')
  })

  it('移动端导入弹窗宽度收窄为视口宽度减边距，不再固定 560px', async () => {
    setViewportWidth(375)
    renderWorkspaceList()

    fireEvent.click(screen.getByTestId('import-workspace-btn'))
    expect(await screen.findByText('导入工作区', { selector: '.ant-modal-title' })).toBeInTheDocument()

    const modal = document.querySelector('.ant-modal') as HTMLElement
    expect(modal).not.toBeNull()
    expect(modal.style.width).toBe('calc(100vw - 32px)')
  })
})

describe('WorkspaceList 桌面端布局回归', () => {
  afterEach(restoreViewport)

  it('桌面端工具栏保持横向排列，搜索框固定 260px，按钮不设置 flex', () => {
    setViewportWidth(1280)
    renderWorkspaceList()

    expect(screen.getByTestId('workspace-list-toolbar')).toHaveStyle({ flexDirection: 'row' })
    expect(getSearchWrapper()).toHaveStyle({ width: '260px' })
    expect(screen.getByTestId('create-workspace-btn').style.flex).toBe('')
    expect(screen.getByTestId('import-workspace-btn').style.flex).toBe('')
  })
})

// ─────────────── 工作区类型：创建时可选用，并决定落地页 ───────────────

describe('WorkspaceList 工作区类型', () => {
  beforeEach(() => {
    // 创建接口回显请求体中的 workspace_type，模拟后端落库后的返回值
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
          workspace_type: body.workspace_type ?? 'data_doc',
          created_by_id: 1,
          created_at: '',
          updated_at: '',
        })
      }),
    )
  })

  it('创建弹窗提供类型选择，默认「数据 + 文档」', async () => {
    renderWorkspaceList()
    fireEvent.click(await screen.findByTestId('create-workspace-btn'))
    const modal = await screen.findByTestId('create-workspace-modal')

    expect(within(modal).getByText('工作区类型')).toBeInTheDocument()
    // 默认选中项渲染为「数据 + 文档」
    expect(within(modal).getByText('数据 + 文档')).toBeInTheDocument()
  })

  it('选择「文档」类型创建后落地到文档页 /w/42/documents', async () => {
    renderWorkspaceList()
    fireEvent.click(await screen.findByTestId('create-workspace-btn'))
    const modal = await screen.findByTestId('create-workspace-modal')

    fireEvent.change(screen.getByLabelText('工作区名称'), { target: { value: '文档区' } })
    // 弹窗内第一个 combobox 为「工作区类型」（其后为公开性）
    fireEvent.mouseDown(within(modal).getAllByRole('combobox')[0]!)
    fireEvent.click(await screen.findByText('文档'))

    const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement
    fireEvent.click(okBtn)

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/w/42/documents')
    }, { timeout: 3000 })
  })

  it('文档类工作区卡片点击进入文档页而非数据表', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({ id: 10, name: '纯文档区', workspace_type: 'doc' })])),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    await user.click(await screen.findByText('纯文档区'))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/documents'))
  })
})

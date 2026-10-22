/**
 * WorkspaceList 组件测试 —— 覆盖创建工作区后的路由跳转行为。
 *
 * 验收：
 *   新建工作区成功后，应自动跳转到新工作区的表列表页 `/w/<id>/tables`。
 *
 * 追加覆盖：加载态 / 空列表空态 / 搜索过滤与无匹配空态 / 点击行进入工作区 /
 * 收藏请求 / 折叠展开 / 表速览 / 收藏分组 / 创建弹窗名称校验 / 创建失败错误提示。
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

/** Location 探针 —— 读取当前 pathname + search 供断言跳转 / 深链 */
function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}{loc.search}</span>
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
            <Route path="/w/:wid/tables/:tid" element={<LocationProbe />} />
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

  it('搜索关键字过滤行，无匹配时显示搜索空态', async () => {
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

  it('点击行主体进入该工作区的表列表页', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({
          id: 10, name: '测试工作区', allow_edit: false, current_user_role: 'owner',
        })])),
    )
    renderWorkspaceList()

    expect(await screen.findByText('测试工作区')).toBeInTheDocument()
    // allow_edit=false 时收起态只给一个「只读」小标记，避免行内堆文案
    expect(screen.getByText('只读')).toBeInTheDocument()

    // 点击行主体（非图标按钮）→ 跳转
    const user = userEvent.setup()
    await user.click(screen.getByText('测试工作区'))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables'))
  })

  it('点击收藏图标发起 togglePin 请求', async () => {
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
    await user.click(await screen.findByTestId('star-btn-10'))

    await waitFor(() => expect(pinBody).toMatchObject({ workspace_id: 10 }))
  })
})

// ─────────────── 折叠 / 展开 / 收藏分组（GitHub 风格行列表） ───────────────

describe('WorkspaceList 可折叠行列表', () => {
  it('默认收起：展开图标可访问属性为 false，详情与「更多操作」不渲染', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({ id: 10, name: '测试工作区' })])),
    )
    renderWorkspaceList()

    const toggle = await screen.findByTestId('workspace-expand-10')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('workspace-detail-10')).not.toBeInTheDocument()
    // 收起态只暴露收藏 + 展开两个图标按钮，设置 / 备份等入口藏进展开区
    expect(screen.queryByTestId('settings-btn-10')).not.toBeInTheDocument()
    expect(screen.queryByTestId('backup-btn-10')).not.toBeInTheDocument()
    expect(screen.getByTestId('star-btn-10')).toBeInTheDocument()
  })

  it('点击展开显示描述、标签与更多操作，再次点击收起', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({
          id: 10, name: '测试工作区', description: '核心业务数据', tags: ['研发', '核心'],
        })])),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    const toggle = await screen.findByTestId('workspace-expand-10')
    await user.click(toggle)

    expect(await screen.findByTestId('workspace-detail-10')).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('核心业务数据')).toBeInTheDocument()
    expect(screen.getByText('研发')).toBeInTheDocument()
    expect(screen.getByTestId('settings-btn-10')).toBeInTheDocument()
    expect(screen.getByTestId('backup-btn-10')).toBeInTheDocument()

    await user.click(toggle)
    await waitFor(() => expect(screen.queryByTestId('workspace-detail-10')).not.toBeInTheDocument())
  })

  it('展开后加载数据表速览，点击表名直达该表', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({ id: 10, name: '测试工作区' })])),
      http.get('/api/v1/workspaces/10/tables', () =>
        HttpResponse.json([
          { id: 100, name: '客户表', record_count: 12 },
          { id: 101, name: '订单表', record_count: 3 },
        ])),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    await user.click(await screen.findByTestId('workspace-expand-10'))

    expect(await screen.findByTestId('workspace-detail-table-100')).toHaveTextContent('客户表')
    await user.click(screen.getByTestId('workspace-detail-table-101'))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/101'))
  })

  it('文档类工作区展开后不请求数据表，仅保留操作入口', async () => {
    let tableRequests = 0
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([makeWs({ id: 10, name: '纯文档区', workspace_type: 'doc' })])),
      http.get('/api/v1/workspaces/10/tables', () => {
        tableRequests += 1
        return HttpResponse.json([])
      }),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    await user.click(await screen.findByTestId('workspace-expand-10'))
    await screen.findByTestId('workspace-detail-10')

    expect(tableRequests).toBe(0)
    expect(screen.queryByTestId('workspace-detail-table-100')).not.toBeInTheDocument()
  })

  it('收藏的工作区分成「已收藏」组并排在最前', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([
          makeWs({ id: 10, name: '普通工作区' }),
          makeWs({ id: 11, name: '收藏工作区', pinned: true }),
        ])),
    )
    renderWorkspaceList()

    const starred = await screen.findByTestId('workspace-group-starred')
    expect(within(starred).getByText('收藏工作区')).toBeInTheDocument()
    expect(within(starred).queryByText('普通工作区')).not.toBeInTheDocument()

    const others = screen.getByTestId('workspace-group-others')
    expect(within(others).getByText('普通工作区')).toBeInTheDocument()
    expect(screen.getByTestId('star-btn-11')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('star-btn-10')).toHaveAttribute('aria-pressed', 'false')
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

// ─────────────── 主页「我的视图」面板与自定义顺序（ADR 0021） ───────────────

/** 「我的视图」默认 fixture：一个私有看板视图 */
const FAVORITE_VIEW = {
  view_id: 300,
  name: '本月进行中',
  view_type: 'kanban',
  is_default: false,
  visibility: 'private',
  filter_count: 2,
  sort_count: 1,
  table_id: 100,
  table_name: '客户表',
  workspace_id: 10,
  workspace_name: '测试工作区',
  updated_at: null,
}

describe('WorkspaceList 我的视图面板', () => {
  it('渲染收藏视图行、计数与「工作区 › 数据表」路径', async () => {
    server.use(
      http.get('/api/v1/accounts/preferences', () => HttpResponse.json({
        active_views: {}, workspace_order: [], favorite_view_ids: [300],
      })),
      http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json([FAVORITE_VIEW])),
    )
    renderWorkspaceList()

    const row = await screen.findByTestId('my-view-row-300')
    expect(row).toHaveTextContent('本月进行中')
    expect(row).toHaveTextContent('测试工作区 › 客户表')
    expect(screen.getByTestId('my-views-count')).toHaveTextContent('1')
  })

  it('无收藏时展示引导空态（指向视图栏星标）', async () => {
    renderWorkspaceList()

    expect(await screen.findByTestId('my-views-empty')).toHaveTextContent('还没有收藏的视图')
    expect(screen.getByText('在数据表的视图栏点击星标即可收藏')).toBeInTheDocument()
  })

  it('展开行显示详情，点击「打开视图」跳到带 view 参数的深链', async () => {
    server.use(
      http.get('/api/v1/accounts/preferences', () => HttpResponse.json({
        active_views: {}, workspace_order: [], favorite_view_ids: [300],
      })),
      http.get('/api/v1/accounts/preferences/favorite-views', () => HttpResponse.json([FAVORITE_VIEW])),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    await user.click(await screen.findByTestId('my-view-expand-300'))

    const detail = await screen.findByTestId('my-view-detail-300')
    expect(detail).toHaveTextContent('筛选 2 条 · 排序 1 条')
    expect(detail).toHaveTextContent('看板')
    expect(detail).toHaveTextContent('仅本人')

    await user.click(screen.getByTestId('my-view-open-300'))
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/100?view=300')
    })
  })

  it('详情内取消收藏：PUT 全量替换为空并移除该行', async () => {
    let favoriteIds: number[] = [300]
    let saved: number[] | undefined
    server.use(
      http.get('/api/v1/accounts/preferences', () => HttpResponse.json({
        active_views: {}, workspace_order: [], favorite_view_ids: favoriteIds,
      })),
      http.get('/api/v1/accounts/preferences/favorite-views', () =>
        HttpResponse.json(favoriteIds.includes(300) ? [FAVORITE_VIEW] : [])),
      http.put('/api/v1/accounts/preferences/favorite-views', async ({ request }) => {
        const body = (await request.json()) as { view_ids: number[] }
        favoriteIds = body.view_ids
        saved = body.view_ids
        return HttpResponse.json({ view_ids: body.view_ids })
      }),
    )
    renderWorkspaceList()

    const user = userEvent.setup()
    await user.click(await screen.findByTestId('my-view-expand-300'))
    await user.click(await screen.findByTestId('my-view-unfavorite-300'))

    await waitFor(() => expect(saved).toEqual([]))
    await waitFor(() => expect(screen.queryByTestId('my-view-row-300')).not.toBeInTheDocument())
    expect(await screen.findByTestId('my-views-empty')).toBeInTheDocument()
  })
})

describe('WorkspaceList 自定义顺序', () => {
  it('按 preferences.workspace_order 调整同组内顺序，未登记 id 按原 id 兜底', async () => {
    server.use(
      http.get('/api/v1/workspaces', () => HttpResponse.json([
        makeWs({ id: 10, name: '工作区A' }),
        makeWs({ id: 11, name: '工作区B' }),
        makeWs({ id: 12, name: '工作区C' }),
      ])),
      http.get('/api/v1/accounts/preferences', () => HttpResponse.json({
        active_views: {}, workspace_order: [12, 10], favorite_view_ids: [],
      })),
    )
    renderWorkspaceList()

    const others = await screen.findByTestId('workspace-group-others')
    await waitFor(() => {
      const ids = within(others).getAllByTestId(/^workspace-row-/).map(el => el.getAttribute('data-testid'))
      expect(ids).toEqual(['workspace-row-12', 'workspace-row-10', 'workspace-row-11'])
    })
  })

  it('搜索过滤时禁用拖拽把手，避免只保存过滤子集', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([
          makeWs({ id: 10, name: '产品研发' }),
          makeWs({ id: 11, name: '市场运营' }),
        ])),
    )
    renderWorkspaceList()

    expect(await screen.findByTestId('workspace-drag-10')).not.toBeDisabled()

    await userEvent.type(screen.getByPlaceholderText('搜索工作区名称/标签...'), '产品')
    await waitFor(() => expect(screen.getByTestId('workspace-drag-10')).toBeDisabled())
  })
})

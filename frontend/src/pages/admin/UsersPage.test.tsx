/**
 * UsersPage 用户管理页组件测试.
 *
 * 覆盖：列表渲染 / 筛选参数 / 编辑二次确认后提交 / 批量操作 / 操作日志抽屉.
 */

import { describe, expect, it, vi, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import UsersPage from './UsersPage'
import { renderProviders } from '@/test/render-providers'
import { server, mockUser } from '@/test/msw'
import type { ResponsiveState } from '@/hooks/useResponsive'

// 可控 useResponsive mock：默认桌面端，移动端用例在其内部切换
let responsiveState: ResponsiveState = {
  deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
  width: 1280, height: 800,
}
vi.mock('@/hooks/useResponsive', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useResponsive')>('@/hooks/useResponsive')
  return { ...actual, useResponsive: () => responsiveState }
})

afterEach(() => {
  vi.restoreAllMocks()
  responsiveState = {
    deviceType: 'desktop', isMobile: false, isTablet: false, isDesktop: true,
    width: 1280, height: 800,
  }
})

const USERS = {
  total: 2,
  items: [
    {
      id: 1, username: 'admin_su', email: 'su@x.com', phone: '13800000001',
      nickname: '系统管理员', role: 'system_admin', is_active: true,
      is_superuser: true, created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2, username: 'bob', email: null, phone: null,
      nickname: '普通用户', role: 'user', is_active: false,
      is_superuser: false, created_at: '2026-01-02T00:00:00Z',
    },
  ],
}

const LOGS = {
  total: 1,
  items: [
    {
      id: 10, action: 'role_change', actor_id: 1, target_user_id: 2,
      detail: { before: { role: 'user' }, after: { role: 'security_admin' } },
      created_at: '2026-01-03T00:00:00Z',
    },
  ],
}

function renderPage() {
  return renderProviders(<UsersPage />, { route: '/admin', initialAuth: { user: mockUser, token: 'fake-token' } })
}

describe('UsersPage 用户管理', () => {
  it('渲染用户列表并展示角色/状态', async () => {
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByText('admin_su')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
    // 昵称与角色标签可能同名（系统管理员），至少渲染一次即可
    expect(screen.getAllByText('系统管理员').length).toBeGreaterThan(0)
    expect(screen.getByText('13800000001')).toBeInTheDocument()
    // bob 被禁用
    expect(screen.getByText('禁用')).toBeInTheDocument()
    // 分页总数
    expect(screen.getByText(/共 2 个用户/)).toBeInTheDocument()
  })

  it('筛选参数随查询下发', async () => {
    // MSW handler 首参为 { request, params, cookies }，显式标注以供断言取 request
    const spy = vi.fn((_info: { request: Request }) => HttpResponse.json(USERS))
    server.use(http.get('/api/v1/accounts/users', spy))
    renderPage()

    await screen.findByText('admin_su')
    const input = screen.getByPlaceholderText('搜索用户名/邮箱/昵称')
    fireEvent.change(input, { target: { value: 'bob' } })
    // AntD Input.Search：点击搜索按钮触发 onSearch（比模拟回车键更可靠）
    fireEvent.click(document.querySelector('.ant-input-search-button') as HTMLElement)

    await waitFor(() => {
      const calls = spy.mock.calls.filter(([info]) => new URL(info.request.url).searchParams.get('keyword') === 'bob')
      expect(calls.length).toBeGreaterThan(0)
    })
  })

  it('编辑保存前弹出二次确认，确认后提交 PATCH', async () => {
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.patch('/api/v1/accounts/users/2', () => HttpResponse.json(USERS.items[1])),
    )
    renderPage()

    // 打开 bob 的编辑弹窗
    fireEvent.click((await screen.findAllByText('编辑'))[1])
    expect(await screen.findByText(/编辑用户：bob/)).toBeInTheDocument()

    // 修改昵称产生实际变更（无变更时组件会拦截保存）
    fireEvent.change(screen.getByLabelText('昵称'), { target: { value: '新昵称' } })
    fireEvent.click(screen.getByRole('button', { name: '保 存' }))
    // 二次确认弹窗
    expect(await screen.findByText('确认保存对该用户的修改？', { selector: '.ant-modal-title' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: '确认保存' }))

    expect(await screen.findByText('用户已更新，变更已记录到操作日志')).toBeInTheDocument()
  })

  it('勾选用户后批量禁用走确认并提交 batch', async () => {
    const batchHandler = vi.fn(() =>
      HttpResponse.json({ total: 1, succeeded: 1, failed: 0, results: [{ user_id: 2, username: 'bob', success: true }] }),
    )
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.post('/api/v1/accounts/users/batch', batchHandler),
    )
    renderPage()

    await screen.findByText('bob') // 等表格行渲染完成，行选择复选框才存在
    fireEvent.click((await screen.findAllByRole('checkbox'))[1])
    expect(await screen.findByText(/已选择 1 个用户/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '批量禁用' }))
    // Popconfirm 气泡确认
    fireEvent.click(await screen.findByRole('button', { name: '确认禁用' }))
    // Popconfirm 确认后进入 Modal.confirm，再次确认
    fireEvent.click(await screen.findByRole('button', { name: '确认执行' }))

    await waitFor(() => expect(batchHandler).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/批量操作完成：成功 1 项/)).toBeInTheDocument()
  })

  it('打开日志抽屉展示权限变更历史（before/after）', async () => {
    server.use(
      http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)),
      http.get('/api/v1/accounts/users/2/audit-logs', () => HttpResponse.json(LOGS)),
    )
    renderPage()

    fireEvent.click((await screen.findAllByText('日志'))[1])
    expect(await screen.findByText(/操作日志：bob/)).toBeInTheDocument()
    expect(await screen.findByText('角色变更')).toBeInTheDocument()
    expect(screen.getByText(/user.*→.*security_admin/)).toBeInTheDocument()
  })
})

describe('UsersPage 移动端适配', () => {
  it('窄屏下筛选控件整行排布，表格保留列宽并横向滚动', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByText('admin_su')).toBeInTheDocument()

    // 筛选控件整行（避免固定宽度在手机上与相邻控件互相挤压）
    const searchInput = screen.getByPlaceholderText('搜索用户名/邮箱/昵称')
    expect((searchInput.closest('.ant-input-group-wrapper') as HTMLElement).style.width).toBe('100%')

    // 窄屏不再渲染宽表格：改为卡片列表（一屏一实体，无需左右滑动看角色/操作）
    expect(document.querySelector('.ant-table')).toBeNull()
    expect(screen.getByTestId('users-mobile-list')).toBeInTheDocument()
    expect(screen.getByTestId('user-card-1')).toHaveTextContent('admin_su')
  })

  it('桌面端筛选控件保持既有固定宽度', async () => {
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    await screen.findByText('admin_su')
    const searchInput = screen.getByPlaceholderText('搜索用户名/邮箱/昵称')
    expect((searchInput.closest('.ant-input-group-wrapper') as HTMLElement).style.width).toBe('220px')

    // 桌面端仍是表格：内容容器横向滚动 + 表格按内容宽度展开（列宽不被压成逐字换行，滚动兜底）
    const content = document.querySelector('.ant-table-content') as HTMLElement
    const table = content.querySelector('table') as HTMLElement
    expect(content.style.overflowX).toBe('auto')
    expect(table.style.width).toBe('max-content')
    const colWidths = [...document.querySelectorAll('.ant-table colgroup col')].map(
      c => (c as HTMLElement).style.width,
    )
    expect(colWidths).toContain('120px') // 昵称列
    expect(colWidths).toContain('180px') // 邮箱列
  })

  it('窄屏改为卡片列表：一屏一实体，角色/状态/操作直接可见', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByTestId('users-mobile-list')).toBeInTheDocument()
    // 不再渲染宽表格
    expect(document.querySelector('.ant-table')).toBeNull()
    const card = screen.getByTestId('user-card-1')
    expect(card).toHaveTextContent('admin_su')
    expect(card).toHaveTextContent('su@x.com')
    expect(card).toHaveTextContent('系统管理员')
    expect(card).toHaveTextContent('超管')
    expect(card).toHaveTextContent('启用')
    expect(within(card).getByText('编辑')).toBeInTheDocument()
    expect(within(card).getByText('日志')).toBeInTheDocument()
    // 分页信息保留
    expect(screen.getByText('共 2 个用户')).toBeInTheDocument()
  })

  it('窄屏卡片勾选可参与批量操作', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    await screen.findByTestId('users-mobile-list')
    fireEvent.click(screen.getByLabelText('选择用户 bob'))

    expect(await screen.findByText(/已选择 1 个用户/)).toBeInTheDocument()
  })

  it('窄屏卡片「编辑」打开编辑弹窗', async () => {
    responsiveState = {
      deviceType: 'mobile', isMobile: true, isTablet: false, isDesktop: false,
      width: 390, height: 844,
    }
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    fireEvent.click(within(await screen.findByTestId('user-card-1')).getByText('编辑'))

    expect(await screen.findByText('编辑用户：admin_su')).toBeInTheDocument()
  })

  it('桌面端仍为表格，不渲染卡片列表', async () => {
    server.use(http.get('/api/v1/accounts/users', () => HttpResponse.json(USERS)))
    renderPage()

    expect(await screen.findByText('admin_su')).toBeInTheDocument()
    expect(screen.queryByTestId('users-mobile-list')).toBeNull()
    expect(document.querySelector('.ant-table')).toBeTruthy()
  })
})
